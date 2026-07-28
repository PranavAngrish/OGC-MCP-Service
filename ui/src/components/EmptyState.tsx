import { ArrowUpRight, Database, GitBranch, ScanSearch } from "lucide-react";

const suggestions = [
  {
    icon: ScanSearch,
    label: "Discover data",
    prompt: "What OGC servers and feature collections are available?",
  },
  {
    icon: GitBranch,
    label: "Explore processes",
    prompt: "Show me the geospatial processes I can run and summarize the useful ones.",
  },
  {
    icon: Database,
    label: "Inspect records",
    prompt: "Search the records catalogue for climate or temperature datasets.",
  },
];

export default function EmptyState({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="empty-state">
      <div className="terrain-mark" aria-hidden="true">
        <svg viewBox="0 0 120 120" role="img">
          <path d="M13 78c18-31 35-9 51-35 12-19 28-12 43 4" />
          <path d="M11 91c16-19 35-8 52-24 19-18 31-9 46 1" />
          <circle cx="75" cy="31" r="5" />
        </svg>
      </div>
      <span className="eyebrow">OGC intelligence, conversationally</span>
      <h1>Ask the landscape<br />a better question.</h1>
      <p>
        Terra connects a reasoning model to trusted OGC APIs through MCP—so answers are grounded
        in live servers, explicit tools, and auditable process runs.
      </p>
      <div className="suggestion-grid">
        {suggestions.map(({ icon: Icon, label, prompt }) => (
          <button key={label} onClick={() => onSelect(prompt)}>
            <span><Icon size={17} /></span>
            <div><strong>{label}</strong><small>{prompt}</small></div>
            <ArrowUpRight size={16} />
          </button>
        ))}
      </div>
    </div>
  );
}
