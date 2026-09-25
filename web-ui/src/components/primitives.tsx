import type { ReactNode } from "react";
import type { AssetState, Ratio } from "../types";

export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`chip ${className}`}>{children}</span>;
}

export function Button({
  children,
  variant = "secondary",
  onClick,
  type = "button",
  disabled = false,
  className = "",
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "quiet" | "danger";
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button className={`button button-${variant} ${className}`} onClick={onClick} type={type} disabled={disabled}>
      {children}
    </button>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 80 ? "high" : score >= 60 ? "mid" : "low";
  return <span className={`score-badge score-${tone}`}>{score}</span>;
}

export function StateChip({ state }: { state: AssetState | string }) {
  return <span className={`state-chip state-${state}`}>{state.replace("_", " ")}</span>;
}

export function ChannelChip({ children }: { children: React.ReactNode }) {
  return <span className="channel-chip">{children}</span>;
}

export function RatioBadge({ ratio }: { ratio: Ratio | string }) {
  return <span className="ratio-badge">{ratio}</span>;
}

export function DurationBadge({ duration }: { duration: number }) {
  const seconds = Math.max(0, Math.round(duration));
  return <span className="duration-badge">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</span>;
}
