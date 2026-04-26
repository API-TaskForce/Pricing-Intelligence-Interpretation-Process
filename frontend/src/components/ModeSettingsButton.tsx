import { useEffect, useRef, useState } from "react";
import { useAppMode, QueryMode } from "../context/appModeContext";

const MODES: { value: QueryMode; label: string; description: string }[] = [
  {
    value: "guided",
    label: "Guided",
    description:
      "If the question is ill-posed, H.A.R.V.E.Y. will ask you to clarify the missing consumption parameters before answering.",
  },
  {
    value: "automatic",
    label: "Autonomous",
    description:
      "Uses a pre-loaded configuration. Whether the question is complete or ill-posed, it answers immediately using the configured consumption mode (fastest, slowest, safest…).",
  },
];

export default function ModeSettingsButton() {
  const { queryMode, setQueryMode } = useAppMode();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (e: MouseEvent | TouchEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [open]);

  return (
    <div ref={ref} className="mode-settings-wrapper">
      <button
        type="button"
        className="mode-settings-btn"
        aria-label="Query mode settings"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span className="mode-settings-label">
          {queryMode === "guided" ? "Guided" : "Autonomous"}
        </span>
      </button>

      {open && (
        <div className="mode-settings-dropdown" role="menu">
          <p className="mode-settings-title">Query Mode</p>
          {MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              role="menuitem"
              className={`mode-settings-option${queryMode === mode.value ? " mode-settings-option--active" : ""}`}
              onClick={() => { setQueryMode(mode.value); setOpen(false); }}
            >
              <span className="mode-settings-option-label">{mode.label}</span>
              <span className="mode-settings-option-desc">{mode.description}</span>
              {queryMode === mode.value && (
                <svg
                  className="mode-settings-check"
                  xmlns="http://www.w3.org/2000/svg"
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
