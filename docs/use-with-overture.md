---
sidebar_position: 2
title: Use with Overture
description: Turning the catalog on, and what Overture does with it.
---

# Use with Overture

OvertureDB is on by default in Overture: it downloads the catalog on its first
start, keeps it up to date and offers its selections next to your media
server's artwork, ready to save to your library. **Settings -> OvertureDB** in
Overture holds **Enable OvertureDB**, **Trust OvertureDB's No theme flag** and
**Browse OvertureDB in the sidebar**.

## Automatic runs

Schedule **Sync** and **Assets** in Overture with OvertureDB as the artwork
source and OvertureDB, ThemerrDB or both for themes, and new media gets its
artwork and theme as soon as the catalog covers it. Assets skips saved choices
by default, so your own picks stay and the catalog fills the gaps around them.
See [Operations](/overture/features/operations) in the Overture docs.

## Browsing

Flip the switch beside the logo in Overture to browse the whole catalog,
including titles outside your library, and filter by what is missing. Choices
made there are drafts, ready to contribute; see
[OvertureDB in Overture](/overture/features/overturedb).

## Collection posters

A TMDB collection can hold two posters: its own, and a consistent one in the
layout every consistent poster shares. Overture's **OvertureDB posters**
setting chooses which one your collections get; see
[Art and themes](/overture/features/collections/art-and-themes#overturedb-posters).

## Availability

The catalog links to artwork and videos on their sources. Coverage grows with
contributions, and linked artwork or videos can disappear from their sources;
the [daily health check](maintainers/workflows.md#dataset-health) reports
broken links so they can be replaced. Correct wrong IDs, replace dead links or
remove an entry through a [contribution](contributing/index.md#changing-an-existing-entry).
