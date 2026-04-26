import type { HarveyMode } from "../types";

interface ModeConfig {
  id: HarveyMode;
  label: string;
  description: string;
}

export const MODES: ModeConfig[] = [
  {
    id: "sendgrid-2025",
    label: "Sendgrid 2025",
    description: "Pre-loaded with the Sendgrid 2025 API datasheet",
  },
  {
    id: "sendgrid-2026",
    label: "Sendgrid 2026",
    description: "Pre-loaded with the Sendgrid 2026 API datasheet",
  },
  {
    id: "mailersend",
    label: "Mailersend",
    description: "Pre-loaded with the Mailersend API datasheet",
  },
  {
    id: "peertube",
    label: "PeerTube",
    description: "Pre-loaded with the PeerTube API datasheet",
  },
  {
    id: "dailymotion",
    label: "Dailymotion",
    description: "Pre-loaded with the Dailymotion API datasheet",
  },
];

interface Props {
  activeMode: HarveyMode;
  onModeChange: (mode: HarveyMode) => void;
  disabled?: boolean;
}

function ModeNav({ activeMode, onModeChange, disabled }: Props) {
  return (
    <nav className="mode-nav" aria-label="Harvey mode selector">
      {MODES.map((mode) => (
        <button
          key={mode.id}
          type="button"
          className={`mode-tab${activeMode === mode.id ? " mode-tab--active" : ""}`}
          onClick={() => onModeChange(mode.id)}
          disabled={disabled}
          title={mode.description}
        >
          {mode.label}
        </button>
      ))}
    </nav>
  );
}

export default ModeNav;
