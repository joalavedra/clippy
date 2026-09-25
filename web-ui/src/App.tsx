import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, fileUrl, ApiError } from "./api";
import type {
  Asset,
  AssetState,
  Health,
  Job,
  JobEvent,
  JobFormat,
  Platform,
  Project,
  Ratio,
  Render,
} from "./types";
import {
  Button,
  Chip,
  DurationBadge,
  RatioBadge,
  ScoreBadge,
  StateChip,
} from "./components/primitives";

type Screen = "library" | "jobs" | "settings";
type ViewMode = "cards" | "table";

const ratios: Ratio[] = ["9:16", "16:9", "1:1"];
const states: AssetState[] = ["not_planned", "planned", "ready", "posted"];

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatDuration(value: number) {
  const seconds = Math.max(0, Math.round(value));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function projectName(projects: Project[], id: string) {
  return projects.find((project) => project.id === id)?.name ?? id.slice(0, 8);
}

function AppShell({
  screen,
  setScreen,
  projects,
  assets,
  children,
}: {
  screen: Screen;
  setScreen: (screen: Screen) => void;
  projects: Project[];
  assets: Asset[];
  children: ReactNode;
}) {
  const projectCounts = useMemo(() => {
    const counts = new Map<string, number>();
    assets.forEach((asset) => asset.project_ids.forEach((id) => counts.set(id, (counts.get(id) ?? 0) + 1)));
    return counts;
  }, [assets]);
  const nav = [
    { id: "library" as const, label: "Library", icon: "▦" },
    { id: "jobs" as const, label: "Jobs", icon: "↗" },
    { id: "settings" as const, label: "Settings", icon: "⚙" },
  ];
  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="wordmark"><span className="wordmark-mark">✦</span> Clippy</div>
        <div className="rail-label">Workspace</div>
        <nav className="nav-list">
          {nav.map((item) => (
            <button
              className={`nav-item ${screen === item.id ? "nav-active" : ""}`}
              key={item.id}
              onClick={() => setScreen(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>{item.label}
            </button>
          ))}
          {["Search", "Calendar", "Favorites", "Channels"].map((label) => (
            <button className="nav-item nav-disabled" key={label} disabled>
              <span className="nav-icon">·</span>{label}<Chip className="soon-chip">soon</Chip>
            </button>
          ))}
        </nav>
        <div className="rail-divider" />
        <div className="rail-section-head"><span>Projects</span><span className="muted-count">{projects.length}</span></div>
        <div className="project-list">
          {projects.map((project) => (
            <button className="project-nav" key={project.id} onClick={() => setScreen("library")}>
              <span className={`project-dot project-${project.platform}`} />
              <span className="project-name">{project.name}</span>
              <span className="project-count">{projectCounts.get(project.id) ?? 0}</span>
            </button>
          ))}
          {!projects.length && <div className="rail-empty">No projects yet</div>}
        </div>
        <div className="rail-footer">Clippy Library v1</div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}

function FilterBar({
  projects,
  project,
  setProject,
  ratio,
  setRatio,
  score,
  setScore,
  state,
  setState,
  favorites,
  setFavorites,
  search,
  setSearch,
}: {
  projects: Project[];
  project: string;
  setProject: (value: string) => void;
  ratio: string;
  setRatio: (value: string) => void;
  score: string;
  setScore: (value: string) => void;
  state: string;
  setState: (value: string) => void;
  favorites: boolean;
  setFavorites: (value: boolean) => void;
  search: string;
  setSearch: (value: string) => void;
}) {
  return (
    <div className="filter-bar">
      <select value={project} onChange={(event) => setProject(event.target.value)}><option value="">All projects</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select>
      <select value={ratio} onChange={(event) => setRatio(event.target.value)}><option value="">Any render</option>{ratios.map((item) => <option value={item} key={item}>{item}</option>)}</select>
      <select value={score} onChange={(event) => setScore(event.target.value)}><option value="">All scores</option><option value="60">60+</option><option value="70">70+</option><option value="80">80+</option></select>
      <select value={state} onChange={(event) => setState(event.target.value)}><option value="">Any state</option>{states.map((item) => <option value={item} key={item}>{item.replace("_", " ")}</option>)}</select>
      <button className={`filter-favorite ${favorites ? "filter-selected" : ""}`} onClick={() => setFavorites(!favorites)}>★ Favorites</button>
      <label className="search-box"><span>⌕</span><input placeholder="Search title or hook" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
    </div>
  );
}

function AssetCard({
  asset,
  projects,
  onOpen,
  onFavorite,
}: {
  asset: Asset;
  projects: Project[];
  onOpen: () => void;
  onFavorite: () => void;
}) {
  const render = asset.renders[0];
  return (
    <article className="asset-card" onClick={onOpen}>
      <div className="thumb-frame">
        {render?.thumb_url ? <img src={fileUrl(render.thumb_url) ?? undefined} alt="" /> : <div className="thumb-placeholder"><span>{render?.ratio ?? "clip"}</span><small>No preview</small></div>}
        <div className="card-score"><ScoreBadge score={asset.viral_score} /></div>
        {render && <div className="card-duration"><DurationBadge duration={render.duration} /></div>}
        <button className={`favorite-button ${asset.favorite ? "favorite-on" : ""}`} onClick={(event) => { event.stopPropagation(); onFavorite(); }} aria-label="Toggle favorite">★</button>
      </div>
      <div className="asset-card-body">
        <h3>{asset.title}</h3>
        <div className="asset-subline">
          <span className="project-chips">{asset.project_ids.map((id) => <Chip key={id}>{projectName(projects, id)}</Chip>)}</span>
          <span className="render-badges">{asset.renders.map((item) => <RatioBadge ratio={item.ratio} key={item.id} />)}</span>
        </div>
        <div className="asset-meta"><StateChip state={asset.state} /><span>{formatDate(asset.created_at)}</span></div>
      </div>
    </article>
  );
}

function AssetTable({
  assets,
  projects,
  onOpen,
  onFavorite,
  onState,
}: {
  assets: Asset[];
  projects: Project[];
  onOpen: (asset: Asset) => void;
  onFavorite: (asset: Asset) => void;
  onState: (asset: Asset, state: AssetState) => void;
}) {
  return (
    <div className="asset-table-wrap">
      <table className="asset-table"><thead><tr><th>Date</th><th>Video</th><th>Renders</th><th>State</th><th>★</th></tr></thead>
        <tbody>{assets.map((asset) => <tr key={asset.id}>
          <td className="muted-cell">{formatDate(asset.created_at)}</td>
          <td><button className="table-video" onClick={() => onOpen(asset)}><span className="table-thumb">{asset.renders[0]?.thumb_url ? <img src={fileUrl(asset.renders[0].thumb_url) ?? undefined} alt="" /> : "—"}</span><span><strong>{asset.title}</strong><small>{projectName(projects, asset.project_ids[0] ?? "")}</small></span><ScoreBadge score={asset.viral_score} /></button></td>
          <td><div className="table-ratios">{asset.renders.map((render) => <RatioBadge ratio={render.ratio} key={render.id} />)}</div></td>
          <td><select value={asset.state} onChange={(event) => onState(asset, event.target.value as AssetState)}><option value="not_planned">not planned</option><option value="planned">planned</option><option value="ready">ready</option><option value="posted">posted</option></select></td>
          <td><button className={`table-star ${asset.favorite ? "favorite-on" : ""}`} onClick={() => onFavorite(asset)}>★</button></td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}

function stripToken(url: string): string {
  return url.replace(/[?&]token=[^&]*/, "");
}

function tokenExpiresSoon(url: string, marginSeconds = 15 * 60): boolean {
  const match = /[?&]token=(\d+)\./.exec(url);
  if (!match) return false;
  return Number(match[1]) <= Date.now() / 1000 + marginSeconds;
}

function AssetDrawer({
  asset,
  projects,
  onClose,
  onPatch,
}: {
  asset: Asset;
  projects: Project[];
  onClose: () => void;
  onPatch: (asset: Asset, patch: { state?: AssetState; favorite?: boolean }) => void;
}) {
  const [selectedRenderId, setSelectedRenderId] = useState<string | null>(asset.renders[0]?.id ?? null);
  const [tab, setTab] = useState<"transcript" | "social" | "covers">("transcript");
  useEffect(() => setSelectedRenderId(asset.renders[0]?.id ?? null), [asset.id]);
  const selected: Render | undefined = asset.renders.find((render) => render.id === selectedRenderId) ?? asset.renders[0];
  const setSelected = (render: Render) => setSelectedRenderId(render.id);
  const [videoSrc, setVideoSrc] = useState<string | undefined>(fileUrl(selected?.url) ?? undefined);
  useEffect(() => {
    const next = fileUrl(selected?.url) ?? undefined;
    setVideoSrc((current) => {
      if (!current || !next) return next;
      if (stripToken(current) !== stripToken(next)) return next;
      return tokenExpiresSoon(current) ? next : current;
    });
  }, [selected?.id, selected?.url]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  const copy = (value: string) => navigator.clipboard?.writeText(value);
  const socialMetadata = asset.metadata.metadata;
  return (
    <div className="drawer-layer">
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="asset-drawer">
        <div className="drawer-header"><div><div className="eyebrow">CLIP {asset.clip_id}</div><h2>{asset.title}</h2><div className="drawer-project">{asset.project_ids.map((id) => <Chip key={id}>{projectName(projects, id)}</Chip>)}</div></div><button className="close-button" onClick={onClose}>×</button></div>
        <div className="drawer-summary"><ScoreBadge score={asset.viral_score} />{selected && <DurationBadge duration={selected.duration} />}<StateChip state={asset.state} /></div>
        <div className="format-toggle">{asset.renders.map((render) => <button className={selected?.id === render.id ? "format-selected" : ""} key={render.id} onClick={() => setSelected(render)}>{render.ratio === "9:16" ? "Vertical" : render.ratio === "16:9" ? "Horizontal" : "Square"}<small>{render.ratio}</small></button>)}</div>
        {selected && <video className={`drawer-video ratio-${selected.ratio.replace(":", "-")}`} controls src={videoSrc} />}
        <div className="drawer-tabs">{(["transcript", "social", "covers"] as const).map((item) => <button className={tab === item ? "tab-active" : ""} key={item} onClick={() => setTab(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}</div>
        <div className="drawer-panel">
          {tab === "transcript" && <div className="copy-blocks"><CopyBlock label="Hook" value={asset.hook_line} onCopy={copy} /><CopyBlock label="Why it works" value={asset.rationale} onCopy={copy} /></div>}
          {tab === "social" && <div className="copy-blocks"><CopyBlock label="Title" value={socialMetadata?.title ?? asset.title} onCopy={copy} /><CopyBlock label="Description" value={socialMetadata?.description ?? "No description yet"} onCopy={copy} /><div><div className="block-label">Hashtags</div><div className="hashtag-list">{(socialMetadata?.hashtags ?? asset.hashtags).map((tag) => <Chip key={String(tag)}>#{String(tag).replace(/^#/, "")}</Chip>)}</div></div></div>}
          {tab === "covers" && <div className="empty-panel"><span className="empty-icon">✦</span><strong>Cover builder coming soon</strong><small>Headline suggestions and layout presets will land here.</small></div>}
        </div>
        <div className="drawer-footer"><select value={asset.state} onChange={(event) => onPatch(asset, { state: event.target.value as AssetState })}><option value="not_planned">not planned</option><option value="planned">planned</option><option value="ready">ready</option><option value="posted">posted</option></select><button className={`drawer-star ${asset.favorite ? "favorite-on" : ""}`} onClick={() => onPatch(asset, { favorite: !asset.favorite })}>★</button>{selected && <a className="button button-primary download-button" href={fileUrl(selected.url) ?? "#"} download>Download</a>}</div>
      </aside>
    </div>
  );
}

function CopyBlock({ label, value, onCopy }: { label: string; value: string; onCopy: (value: string) => void }) {
  return <div className="copy-block"><div className="block-label">{label}<button className="copy-button" onClick={() => onCopy(value)}>Copy</button></div><p>{value}</p></div>;
}

function Library({ assets, projects, onPatch, reloadAssets }: { assets: Asset[]; projects: Project[]; onPatch: (asset: Asset, patch: { state?: AssetState; favorite?: boolean }) => void; reloadAssets: () => Promise<void> }) {
  const [project, setProject] = useState("");
  const [ratio, setRatio] = useState("");
  const [score, setScore] = useState("");
  const [state, setState] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewMode>("cards");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    if (selectedId) void reloadAssets();
  }, [selectedId, reloadAssets]);
  useEffect(() => {
    const refresh = () => void reloadAssets();
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, 10 * 60 * 1000);
    return () => {
      window.removeEventListener("focus", refresh);
      window.clearInterval(timer);
    };
  }, [reloadAssets]);
  const filtered = useMemo(() => assets.filter((asset) => {
    const text = `${asset.title} ${asset.hook_line}`.toLowerCase();
    return (!project || asset.project_ids.includes(project))
      && (!ratio || asset.renders.some((render) => render.ratio === ratio))
      && (!score || asset.viral_score >= Number(score))
      && (!state || asset.state === state)
      && (!favorites || asset.favorite)
      && (!search || text.includes(search.toLowerCase()));
  }), [assets, project, ratio, score, state, favorites, search]);
  const selected = assets.find((asset) => asset.id === selectedId);
  return (
    <section className="page">
      <header className="page-header"><div><div className="eyebrow">CONTENT LIBRARY</div><h1>Library</h1><p className="page-subtitle">{assets.length} clips across {projects.length} projects</p></div><div className="view-toggle"><button className={view === "cards" ? "view-active" : ""} onClick={() => setView("cards")}>▦ Cards</button><button className={view === "table" ? "view-active" : ""} onClick={() => setView("table")}>☷ Table</button></div></header>
      <FilterBar projects={projects} project={project} setProject={setProject} ratio={ratio} setRatio={setRatio} score={score} setScore={setScore} state={state} setState={setState} favorites={favorites} setFavorites={setFavorites} search={search} setSearch={setSearch} />
      {!filtered.length ? <div className="empty-state"><span className="empty-icon">✦</span><h2>No clips yet</h2><p>Create a job to generate clips.</p></div> : view === "cards" ? <div className="asset-grid">{filtered.map((asset) => <AssetCard key={asset.id} asset={asset} projects={projects} onOpen={() => setSelectedId(asset.id)} onFavorite={() => onPatch(asset, { favorite: !asset.favorite })} />)}</div> : <AssetTable assets={filtered} projects={projects} onOpen={(asset) => setSelectedId(asset.id)} onFavorite={(asset) => onPatch(asset, { favorite: !asset.favorite })} onState={(asset, next) => onPatch(asset, { state: next })} />}
      {selected && <AssetDrawer asset={selected} projects={projects} onClose={() => setSelectedId(null)} onPatch={onPatch} />}
    </section>
  );
}

function NewJobForm({ projects, onClose, onCreated }: { projects: Project[]; onClose: () => void; onCreated: () => void }) {
  const [selectedProjects, setSelectedProjects] = useState<string[]>(projects.slice(0, 1).map((project) => project.id));
  const [brief, setBrief] = useState("");
  const [formats, setFormats] = useState<JobFormat[]>([{ ratio: "9:16", min: 8, max: 15 }]);
  const [clips, setClips] = useState(2);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await api<Job>("/api/jobs", { method: "POST", body: JSON.stringify({ project_ids: selectedProjects, brief, formats, clips, options: { story_style: "styled" } }) });
      onCreated();
      onClose();
    } catch (caught) { setError(caught instanceof ApiError ? caught.detail : "Unable to create job"); }
  };
  const updateFormat = (index: number, patch: Partial<JobFormat>) => setFormats(formats.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  return <div className="modal-layer"><div className="modal-scrim" onClick={onClose} /><form className="modal-card" onSubmit={submit}><div className="modal-heading"><div><div className="eyebrow">DIRECTOR RUN</div><h2>New job</h2></div><button className="close-button" type="button" onClick={onClose}>×</button></div><label>Brief<textarea required rows={3} value={brief} onChange={(event) => setBrief(event.target.value)} placeholder="What should these clips be about?" /></label><div className="form-section"><div className="section-title">Projects</div>{projects.map((project) => <label className="checkbox-row" key={project.id}><input type="checkbox" checked={selectedProjects.includes(project.id)} onChange={(event) => setSelectedProjects(event.target.checked ? [...selectedProjects, project.id] : selectedProjects.filter((id) => id !== project.id))} />{project.name}<span className="muted-cell">{project.platform}</span></label>)}</div><div className="form-section"><div className="section-title">Formats</div>{formats.map((format, index) => <div className="format-row" key={`${index}-${format.ratio}`}><select value={format.ratio} onChange={(event) => updateFormat(index, { ratio: event.target.value as Ratio })}>{ratios.map((ratio) => <option value={ratio} key={ratio}>{ratio}</option>)}</select><input type="number" min="1" value={format.min} onChange={(event) => updateFormat(index, { min: Number(event.target.value) })} /><span>to</span><input type="number" min="1" value={format.max} onChange={(event) => updateFormat(index, { max: Number(event.target.value) })} /><button className="icon-button" type="button" onClick={() => setFormats(formats.filter((_, itemIndex) => itemIndex !== index))} disabled={formats.length === 1}>×</button></div>)}<button className="link-button" type="button" onClick={() => setFormats([...formats, { ratio: "16:9", min: 20, max: 30 }])}>+ Add format</button></div><label className="short-label">Clips<input type="number" min="1" max="10" value={clips} onChange={(event) => setClips(Number(event.target.value))} /></label>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" disabled={!selectedProjects.length || !brief}>Create job</Button></div></form></div>;
}

function AddProjectForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({ name: "", platform: "youtube" as Platform, source: "", layout: "single" });
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    try {
      const body = { name: form.name, platform: form.platform, layout: form.layout, ...(form.platform === "local" ? { local_path: form.source } : { url: form.source }) };
      await api<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }); setForm({ name: "", platform: "youtube", source: "", layout: "single" }); onCreated();
    } catch (caught) { setError(caught instanceof ApiError ? caught.detail : "Unable to add project"); }
  };
  return <form className="add-project-form" onSubmit={submit}><div className="section-title">Add project</div><div className="form-grid"><label>Name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>Platform<select value={form.platform} onChange={(event) => setForm({ ...form, platform: event.target.value as Platform })}>{(["youtube", "tiktok", "instagram", "gdrive", "local"] as Platform[]).map((platform) => <option key={platform}>{platform}</option>)}</select></label></div><label>{form.platform === "local" ? "Local path" : "URL"}<input required value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })} placeholder={form.platform === "local" ? "/data/uploads/video.mp4" : "https://youtube.com/watch?v=..."} /></label><label>Layout<select value={form.layout} onChange={(event) => setForm({ ...form, layout: event.target.value })}><option value="single">single</option><option value="podcast">podcast</option></select></label>{error && <div className="form-error">{error}</div>}<Button type="submit" variant="primary">Add project</Button></form>;
}

function Jobs({ jobs, projects, reload }: { jobs: Job[]; projects: Project[]; reload: () => void }) {
  const [showNew, setShowNew] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [events, setEvents] = useState<Record<string, JobEvent[]>>({});
  const expandedJob = jobs.find((job) => job.id === expanded);
  const refreshEvents = async (jobId: string) => {
    const next = await api<JobEvent[]>(`/api/jobs/${jobId}/events`);
    setEvents((current) => ({ ...current, [jobId]: next }));
  };
  useEffect(() => {
    if (!expanded && !jobs.some((job) => job.status === "queued" || job.status === "running")) return;
    const timer = window.setInterval(() => {
      void reload();
      if (expanded) void refreshEvents(expanded);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [expanded, jobs, reload]);
  useEffect(() => {
    if (expanded) void refreshEvents(expanded);
  }, [expanded, expandedJob?.updated_at, expandedJob?.status]);
  const toggleEvents = (job: Job) => {
    if (expanded === job.id) { setExpanded(null); return; }
    setExpanded(job.id);
  };
  return <section className="page"><header className="page-header"><div><div className="eyebrow">PIPELINE</div><h1>Jobs</h1><p className="page-subtitle">Track your director runs and generated assets.</p></div><Button variant="primary" onClick={() => setShowNew(true)}>+ New job</Button></header><div className="job-list">{jobs.length ? jobs.map((job) => <article className="job-row" key={job.id}><div className="job-main" onClick={() => toggleEvents(job)}><div className="job-status-line"><span className={`job-status job-${job.status}`}>{job.status}</span><span className="job-stage">{job.stage}</span><span className="job-date">{formatDate(job.created_at)}</span></div><h3>{job.brief}</h3><div className="job-formats">{job.formats.map((format) => <RatioBadge ratio={`${format.ratio} · ${format.min}-${format.max}s`} key={format.ratio} />)}<span>{job.clips} clips</span></div></div><div className="job-progress"><div className="progress-label"><span>{job.status === "failed" ? job.error : job.stage}</span><strong>{Math.round(job.percent)}%</strong></div><div className="progress-track"><span style={{ width: `${job.percent}%` }} /></div></div>{expanded === job.id && <div className="job-events">{(events[job.id] ?? []).map((event) => <div className="event-row" key={event.id}><span>{formatDate(event.ts)}</span><strong>{event.stage}</strong><span>{event.message || "updated"}</span></div>)}</div>}</article>) : <div className="empty-state compact"><span className="empty-icon">↗</span><h2>No jobs yet</h2><p>Start a new director run to populate your library.</p></div>}</div><AddProjectForm onCreated={reload} />{showNew && <NewJobForm projects={projects} onClose={() => setShowNew(false)} onCreated={reload} />}</section>;
}

function SettingsPage({ health, refreshHealth }: { health: Health | null; refreshHealth: () => void }) {
  const [key, setKey] = useState(localStorage.getItem("clippy_api_key") ?? "");
  const [saved, setSaved] = useState(false);
  const save = () => { localStorage.setItem("clippy_api_key", key.trim()); setSaved(true); window.setTimeout(() => setSaved(false), 1800); };
  return <section className="page"><header className="page-header"><div><div className="eyebrow">WORKSPACE</div><h1>Settings</h1><p className="page-subtitle">Connection and local workspace preferences.</p></div></header><div className="settings-grid"><div className="settings-card"><div className="section-title">Service connection</div><p className="card-description">The API key is stored only in this browser and sent as a request header.</p><label>API key<input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="CLIPPY_API_KEY" /></label><div className="setting-actions"><Button variant="primary" onClick={save}>Save key</Button>{saved && <span className="save-note">Saved</span>}</div></div><div className="settings-card"><div className="section-title">Worker health</div><div className="health-status"><span className={`health-dot ${health?.status === "ok" ? "health-ok" : ""}`} /><strong>{health?.status === "ok" ? "Service online" : "Waiting for service"}</strong></div><div className="health-grid"><div><strong>{health?.worker_alive ? "On" : "Off"}</strong><span>Worker</span></div><div><strong>{health?.queued ?? "—"}</strong><span>Queued</span></div><div><strong>{health?.running ?? "—"}</strong><span>Running</span></div></div><Button variant="secondary" onClick={refreshHealth}>Refresh health</Button></div></div></section>;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("library");
  const [projects, setProjects] = useState<Project[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const loadProjects = async () => setProjects(await api<Project[]>("/api/projects"));
  const loadAssets = useCallback(
    async () => setAssets(await api<Asset[]>("/api/assets")),
    [],
  );
  const refreshAssets = useCallback(async () => {
    try { await loadAssets(); } catch (caught) { setError(caught instanceof ApiError ? caught.detail : "Unable to refresh clips; media links may be stale"); }
  }, [loadAssets]);
  const loadJobs = async () => setJobs(await api<Job[]>("/api/jobs"));
  const loadHealth = async () => setHealth(await api<Health>("/api/health"));
  const reload = async () => { try { await Promise.all([loadProjects(), loadAssets(), loadJobs(), loadHealth()]); } catch (caught) { setError(caught instanceof ApiError ? caught.detail : "Unable to reach the service"); } };
  useEffect(() => { void reload(); }, []);
  const patchAsset = async (asset: Asset, patch: { state?: AssetState; favorite?: boolean }) => {
    try { const updated = await api<Asset>(`/api/assets/${asset.id}`, { method: "PATCH", body: JSON.stringify(patch) }); setAssets((current) => current.map((item) => item.id === updated.id ? updated : item)); } catch (caught) { setError(caught instanceof ApiError ? caught.detail : "Unable to update asset"); }
  };
  return <AppShell screen={screen} setScreen={setScreen} projects={projects} assets={assets}>{error && <div className="global-error">{error}<button onClick={() => setError("")}>×</button></div>}{screen === "library" && <Library assets={assets} projects={projects} onPatch={patchAsset} reloadAssets={refreshAssets} />}{screen === "jobs" && <Jobs jobs={jobs} projects={projects} reload={reload} />}{screen === "settings" && <SettingsPage health={health} refreshHealth={loadHealth} />}</AppShell>;
}
