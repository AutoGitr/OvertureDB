#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: build-contribution-entry.sh <issue-body-file> <issue-title> <labels-file> <output-root>" >&2
}

[ "$#" -eq 4 ] || {
  usage
  exit 2
}

body_file="$1"
issue_title="$2"
labels_file="$3"
output_root="$4"

fail() {
  echo "$1" >&2
  exit 1
}

[ -f "$body_file" ] || fail "Issue body file does not exist: ${body_file}"
[ -f "$labels_file" ] || fail "Labels file does not exist: ${labels_file}"

field() {
  awk -v heading="$1" '
    $0 == "### " heading { capture = 1; next }
    /^### / && capture { exit }
    capture { print }
  ' "$body_file" \
    | sed '/^[[:space:]]*$/d' \
    | sed 's/^_No response_$//'
}

clean_single_line() {
  printf '%s' "$1" | tr -d '\r' | head -n1
}

if grep -qx "movie" "$labels_file"; then
  media_type="movie"
elif grep -qx "show" "$labels_file"; then
  media_type="show"
elif printf '%s' "$issue_title" | grep -q '^\[Movie\]:'; then
  media_type="movie"
elif printf '%s' "$issue_title" | grep -q '^\[Show\]:'; then
  media_type="show"
else
  fail "Issue must use the movie or show contribution form."
fi

title="$(clean_single_line "$(field "Title")")"
year="$(clean_single_line "$(field "Year")")"
tmdb_id="$(clean_single_line "$(field "TMDB ID")")"
tvdb_id="$(clean_single_line "$(field "TVDB ID")")"
imdb_id="$(clean_single_line "$(field "IMDb ID")")"
poster_url="$(clean_single_line "$(field "Poster URL")")"
background_url="$(clean_single_line "$(field "Background URL")")"
youtube_id="$(clean_single_line "$(field "YouTube theme video ID")")"
season_posters="$(field "Season posters")"

[ -n "$title" ] || fail "Missing Title field."

if [ -n "$tmdb_id" ] && ! printf '%s' "$tmdb_id" | grep -Eq '^[0-9]+$'; then
  fail "TMDB ID must contain digits only."
fi

if [ -n "$tvdb_id" ] && ! printf '%s' "$tvdb_id" | grep -Eq '^[0-9]+$'; then
  fail "TVDB ID must contain digits only."
fi

if [ -n "$imdb_id" ] && ! printf '%s' "$imdb_id" | grep -Eq '^tt[0-9]+$'; then
  fail "IMDb ID must use the format tt followed by digits."
fi

if [ "$media_type" = "movie" ]; then
  folder="data/movies"
  candidates=("tmdb:$tmdb_id" "tvdb:$tvdb_id" "imdb:$imdb_id")
else
  folder="data/shows"
  candidates=("tvdb:$tvdb_id" "tmdb:$tmdb_id" "imdb:$imdb_id")
fi

target=""
for candidate in "${candidates[@]}"; do
  value="${candidate#*:}"
  [ -n "$value" ] || continue
  target="${folder}/${candidate%%:*}-${value}.json"
  break
done

[ -n "$target" ] || fail "${media_type} contributions need a TMDB, TVDB, or IMDb ID."

mkdir -p "${output_root}/${folder}"

if [ -e "${output_root}/${target}" ]; then
  fail "Dataset file already exists on main: \`${target}\`. Please update it manually."
fi

seasons_json="$(
  printf '%s\n' "$season_posters" | jq -R -s '
    split("\n")
    | map(select(length > 0 and contains("=")))
    | map(
        capture("^(?<season_num>[0-9]+)=(?<poster_url>.+)$")
        | {
            season_num: (.season_num | tonumber),
            poster_url
          }
      )
  '
)" || fail "Season posters must use season_num=url lines."

if ! jq -n \
    --arg media_type "$media_type" \
    --arg title "$title" \
    --arg year "$year" \
    --arg tmdb_id "$tmdb_id" \
    --arg tvdb_id "$tvdb_id" \
    --arg imdb_id "$imdb_id" \
    --arg poster_url "$poster_url" \
    --arg background_url "$background_url" \
    --arg youtube_id "$youtube_id" \
    --argjson seasons "$seasons_json" \
    'def number_or_null: if . == "" then null else tonumber end;
     def string_or_null: if . == "" then null else . end;
     {
      media_type: $media_type,
      title: $title,
      year: ($year | number_or_null),
      tmdb_id: ($tmdb_id | number_or_null),
      tvdb_id: ($tvdb_id | number_or_null),
      imdb_id: ($imdb_id | string_or_null),
      poster_url: ($poster_url | string_or_null),
      background_url: ($background_url | string_or_null),
      youtube_id_overturedb: ($youtube_id | string_or_null),
      youtube_id_themerrdb: null
    }
    + if $media_type == "show" then { seasons: $seasons } else {} end
    ' > "${output_root}/${target}"; then
  rm -f "${output_root}/${target}"
  fail "Submitted fields could not be converted into dataset JSON. Check numeric year and mapping fields."
fi

printf '%s\n' "$target"
