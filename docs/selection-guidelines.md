# OvertureDB Selection Guidelines

OvertureDB is a curated community catalog of high-resolution artwork and theme music for movies and shows. Rather than storing binary media files, OvertureDB stores verified metadata, direct artwork URLs, and YouTube theme IDs.

Every selection is curated for quality, artistic integrity, and visual continuity across media libraries.

---

## 1. Core Principles

- **Faithful Representation**: Every selection must reflect the tone, aesthetic, and atmosphere of the work.
- **Visual Consistency**: Items belonging to a shared collection, franchise, or director catalog should maintain consistent art styles, framing, and typography.
- **No Spoilers**: Never submit artwork or theme audio that spoils major plot points, twists, character deaths, or climax scenes.
- **Criterion Collection Standard**: Any Criterion film must use a properly formatted Criterion poster. It must use modern Criterion formatting (clean contemporary layout), must not be stretched or distorted, and must feature the authentic, official Criterion cover art.
- **Introducing New Sets**: When contributing items that introduce a new collection or franchise poster set, submit an update to the [Established Poster Sets](#5-established-poster-sets) section of this document so future contributors can maintain visual continuity.

---

## 2. Artwork Standards

### Posters
- **Title Required**: The poster must include the official title of the movie or show.
- **Minimal Text**: Avoid promotional clutter such as taglines, billing blocks, actor names, critic quotes, awards, or release dates unless an item's official style intentionally warrants it.
- **Resolution**: **2000×3000** (2:3 aspect ratio) preferred. High resolution and sharp framing are required.

### Backgrounds (Fanart / Backdrops)
- **Authentic Scenes Only**: Must be a genuine frame or scene taken directly from the movie or show.
- **No Text**: Backgrounds must be clean and textless unless the text is naturally part of the in-universe scene.
- **Resolution**: **3840×2160** (16:9 aspect ratio) preferred; minimum 1920×1080.
- **Strict Prohibition on Character Collages**: Never use "photoshopped" promotional images where characters are artificially assembled, superimposed, or presented as floating heads.

### Season Posters
- **Season Numbering**: Must clearly indicate the season (e.g., "Season 1", "Season 2").
- **Minimal Text**: Avoid additional promotional text or episode titles unless stylistically essential.
- **Resolution**: **2000×3000** (2:3 aspect ratio) preferred.
- **Set Coherence**: All season posters for a show must belong to the same visual set, sharing consistent typography, framing, and art style.

---

## 3. Theme Music Standards

- **Preferred Duration**: **1 to 2 minutes**.
- **Audio Quality**: Clean, high-fidelity audio. The selection must not contain speech intros, dialogue interruptions, voiceovers, video watermarks, sponsor stings, or abrupt cutoffs.
- **No ThemerrDB Duplication**: OvertureDB automatically imports themes from ThemerrDB into a separate field. Do not duplicate an existing ThemerrDB theme. Only submit an OvertureDB theme when providing a distinct, curated, or higher-quality alternative, or when ThemerrDB lacks a theme for the item.

---

## 4. Allowed Sources & URL Formatting

To protect users against security risks and dead links, all artwork URLs must resolve to public HTTPS destinations from the following allowlist:

| Provider | Allowed Host | Path & Format Requirements |
| :--- | :--- | :--- |
| **ThePosterDB** | `theposterdb.com`<br>`www.theposterdb.com` | Must use direct asset path: `/api/assets/<id>`.<br>Do **not** include trailing `/view` or URL fragments (`#`). |
| **TMDB** | `image.tmdb.org` | Direct image path (e.g., `/t/p/original/...`). |
| **Fanart.tv** | `assets.fanart.tv` | Direct image asset path. |
| **TheTVDB** | `artworks.thetvdb.com` | Direct image asset path. |
| **Plex Static** | `metadata-static.plex.tv` | Direct static asset path. |

### Technical Requirements
- **Protocol**: Public HTTPS only. HTTP, IP addresses, custom ports, and credentials are rejected.
- **Image Format**: Direct JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) images. URLs must return valid JPEG or PNG byte signatures.

---

## 5. Established Poster Sets

To maintain visual harmony across shared franchises, use the following established sets when contributing matching items:

| Universe / Collection | Poster Set & Style Reference | Notes |
| :--- | :--- | :--- |
| **Walt Disney Animation Studios** | [ThePosterDB Set 2454](https://theposterdb.com/set/2454) | Canonical animated features. |
| **Walt Disney Animation Shorts** | [ThePosterDB Poster 206944 Style](https://theposterdb.com/poster/206944) | Matching style by users `scoobymcsnack`, `DIIIVOY`, and `HammerActually`. |
| **Pixar Animation Studios** | [ThePosterDB Set 97](https://theposterdb.com/set/97) | Feature films. |
| **Pixar Shorts** | [ThePosterDB Set 11456](https://theposterdb.com/set/11456) | Animated short films. |
| **Studio Ghibli** | [ThePosterDB Set 32965](https://theposterdb.com/set/32965) | Feature films. |
| **Disneynature** | [ThePosterDB Set 11090](https://theposterdb.com/set/11090) | Nature documentary releases. |
| **Marvel Cinematic Universe (MCU)** | [ThePosterDB Set 87082](https://theposterdb.com/set/87082) | MCU movies and series. |
| **James Bond** | [ThePosterDB Set 62004](https://theposterdb.com/set/62004) | EON film franchise. |
| **Ken Burns Documentaries** | [ThePosterDB Poster 218606 Style](https://theposterdb.com/poster/218606) | By user `fwlolx`. |
| **David Attenborough Documentaries** | [ThePosterDB Set 125988](https://theposterdb.com/set/125988) | By user `fwlolx`. |
| **Planet Documentaries** | [ThePosterDB Set 143160](https://theposterdb.com/set/143160) | For David Attenborough's "Planet" series (*Planet Earth*, *Blue Planet*, *Frozen Planet*, etc.). |
| **Apocalypse Documentaries** | [ThePosterDB Set 398222](https://theposterdb.com/set/398222) | Historical documentary series. |

> [!TIP]
> If you create or discover a coherent set for another franchise or collection, use it consistently for all entries in that series and submit a documentation pull request adding it to this table.

---

## 6. Submission & Review Workflow

Contributions are submitted via GitHub Issues and processed into automated pull requests by `@OvertureDB-bot`.

### 1. Submit an Issue
Choose the appropriate issue template:
- **[Movie Contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml)**: Provide title, year, external IDs (TMDB, TVDB, IMDb), poster URL, background URL, and YouTube ID.
- **[Show Contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)**: Provide show metadata, poster, background, YouTube ID, and season posters (`season_number=url`).
- **[Bulk Contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml)**: Attach an exported `overturedb-selections.zip` generated from Overture (**OvertureDB -> Export selections**).

### 2. Modifying Existing Entries
If your submission updates an existing catalog item (e.g., higher resolution, textless artwork, or fixed links):
- You **must** replace the default text in **Reason for modification** with a specific justification.
- Submissions leaving the default placeholder text are paused automatically to protect existing entries from unintended overwrites.

### 3. Automated Validation & Review
1. Once opened, the automated preview workflow validates external IDs, verifies HTTPS URLs against the allowlist, and confirms JPEG/PNG headers.
2. The bot generates an issue comment previewing the changes and visual diff.
3. A maintainer reviews the submission and approves it:
   - `@OvertureDB-bot approve` — Generates a reviewed pull request and merges the selection.
   - `@OvertureDB-bot reject [reason]` — Closes the issue with feedback.
4. Maintainers can also edit the issue description directly to fine-tune URLs before approving.
