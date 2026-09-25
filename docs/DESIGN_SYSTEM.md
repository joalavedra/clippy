# Clippy — product & design system

Reference: Alberto Rosas' unpublished "media creation platform"
(https://x.com/albertorosasg/status/2092656573927870968). Studied from the
demo video; what follows is what is visible in it, translated into a design
system for Clippy's UI. Where the video does not show something, it is marked
as our addition.

## 1. Product model (what the UI is organised around)

The reference is a **content system**, not a clip editor: raw footage goes in
once, and the UI is about triaging, scheduling and publishing what the
pipeline produced. Five surfaces:

| Surface | Purpose | Clippy equivalent |
|---|---|---|
| **Library** | Grid/table of every asset (full videos and clips) across projects, with filters and a virality score badge | jobs' rendered clips + recipes |
| **Asset drawer** | Right-side panel over the library: player, Horizontal/Vertical toggle, tabs *Transcript · Clips · Social · Covers*, schedule + push controls | one clip of a recipe, with its format variants, captions, metadata |
| **Planner / Calendar** | Month / week / list of scheduled posts; per-post channel rows (IG, LinkedIn, X) with push state (Scheduled → Pushed → Posted); "Smart plan", "Sync from Buffer" | publish stage; per-format clip × channel |
| **Search footage** | Semantic search over *what is said* (transcript) and *what is seen* (visual index); results show ranked moments with timestamps and highlighted words | transcript cache + (our addition) visual index feeding the director |
| **Channels / Settings** | Connected accounts, brand voice rules ("founder content is not allowed on @getdidit") | publish targets, brand constraints passed to the director prompt |

Core objects, as the UI exposes them:

```
Project  (a shoot / raw upload; e.g. "raw-2026-06-01", "full-office-attico")
 └─ Asset  kind: full | clip
     ├─ score (0-100 badge), duration, title (auto), project, people tags
     ├─ renders: horizontal 16:9, vertical 9:16  (toggle in drawer)
     ├─ transcript (word-level, karaoke captions burned in)
     ├─ social copy per channel (LinkedIn/X/IG) with live preview
     ├─ covers: headline suggestions (9), {braces} = accent-colour words,
     │          layout presets (Letterbox bottom/top/split, Diptych, Blur hero, Editorial)
     └─ schedule: state Not planned | Planned | Ready | Posted, date+time slot, channels
```

This maps 1:1 to our recipe model: `Project = source`, `Asset(clip) = recipe clip`,
`renders = --formats`, `social copy = metadata`, `covers = thumbnail stage`.
What we do not have yet: score badge surfaced from `viral_score`, covers with
layout presets, scheduling/publish state, visual search.

## 2. Visual language

Observed: quiet, dense, utilitarian SaaS ("Linear/Notion-like"), content
thumbnails carry all the colour.

**Colour**
```
--bg            #F5F6F8   app background (cool light grey)
--surface       #FFFFFF   cards, drawers, table rows
--border        #E6E8EC   1px hairlines
--text          #111318
--text-muted    #6B7280
--accent        #2F6BFF   primary buttons, active tab, selected card ring, spoken-match highlight
--accent-soft   #E8EFFF   chips, selected filter, active nav item
--success       #16A34A   score badge ≥ 80, "Posted"
--warning       #D97706   "Ready", buffer partial
--danger        #DC2626   destructive, "Voice" rule violations
--score-high    green pill   ≥ 80
--score-mid     amber pill   60–79
--score-low     grey pill    < 60
```
Channel identity colours are used only as small chips (IG pink, LinkedIn blue, X black).

**Type** — single sans (Inter or similar), 13px base in dense views, 15px in
drawers, 20px page titles. Titles are auto-cased ("Why We Make These Videos").
Monospace only for slugs (`didit-office-walkthrough`).

**Shape & space** — 8px grid; cards radius 12px, chips 999px, inputs 8px;
1px borders instead of shadows; selected card gets a 2px accent ring. Drawer
width ≈ 440px, docked right, over the grid (grid stays visible and dimmed).

**Motion** — none visible beyond default transitions; the product moves fast.

## 3. Component inventory

| Component | Spec |
|---|---|
| `AppShell` | 220px left nav (workspace switcher, Library/Search/Calendar/Favorites/Channels/Settings, then a Projects list with counts) + content area |
| `FilterBar` | Row of pill dropdowns: All projects · All/Full/Clip · score buckets (All/60+/70+) · Any render · Any date · Any slot · Any state · Anyone · ★ Favorites · search box. Second row: Columns, more |
| `ViewToggle` | Table / Cards |
| `AssetCard` | 16:9 thumb with score badge (top-right, colour by bucket) and duration (bottom-right); title (2 lines max); project slug + kind chip; state chip + date; action row: push, open, re-render, ★, archive |
| `AssetTable` | Same data as rows: Date · Video (thumb, title, slug, score) · Channels (chip per channel with push state) · Buffer · Status (select) · Actions |
| `AssetDrawer` | Header (thumb, title, project, workspace, duration; People tags; state + next slot; icon actions) → `FormatToggle` Horizontal/Vertical → `Player` (speed 1x/1.5x/2x, mute) → `Tabs` Transcript/Clips/Social/Covers → footer: state select, Remove from calendar, Push to Buffer, date, time, Save |
| `ClipGrid` (Clips tab) | 3-col mini cards: score badge, ratio badge (9:16), duration, title |
| `SocialComposer` (Social tab) | Editing-channel selector; textarea with char count (729/3000); "Live preview" rendered as the target network's post card |
| `CoverBuilder` (Covers tab) | Headline input with `{braces}` for accent words + "Highlight selection"; 9 AI suggestions as selectable chips; Layout presets grid with "Best for landscape" tag |
| `Planner` | Month/Week/List; filter row (workspace, project, channel, state counts Planned/Ready/Posted, score); List = `AssetTable` grouped by date; toolbar: Buffer status, Sync from Buffer, Smart plan, Sync to Drive |
| `SearchFootage` | Big search input; match summary chips ("12 by speech · 16 by look · 228 ms · 126 indexed"); filter All/Spoken/Visual/project; result = hero thumb + ranked title + project/duration + Spoken%/Visual% bars + "Why it matched · N moments" strip of timestamped thumbs with highlighted transcript |
| `ScoreBadge`, `StateChip`, `ChannelChip`, `RatioBadge`, `DurationBadge` | small primitives shared by all of the above |

## 4. How this shapes Clippy's next stages

- The service layer's data model should be the object tree in §1 (project →
  asset → renders / copy / covers / schedule), not "jobs" — jobs are an
  implementation detail shown as a small progress state on the asset.
- Every render must carry `viral_score`, `duration`, `ratio`, `title`,
  `project`, `state` so the Library can be built directly on the API.
- Covers = a new thumbnail stage with layout presets; headline generation can
  reuse the director's metadata call.
- Search footage = transcript search first (we have word-level text); visual
  index later.
- Brand "Voice" rules become constraints in the director prompt and a
  validation warning on the asset.
