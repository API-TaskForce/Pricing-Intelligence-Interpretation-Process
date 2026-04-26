import type { PromptPreset } from "../types";

interface Props {
  presets: PromptPreset[];
  activePresetId: string | null;
  onSelect: (preset: PromptPreset) => void;
}

function DemoPresetPanel({ presets, activePresetId, onSelect }: Props) {
  return (
    <div className="demo-preset-panel">
      <p className="demo-preset-panel-title">Preguntas disponibles</p>
      <div className="demo-preset-grid">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={`prompt-suggestion-card${activePresetId === preset.id ? " prompt-suggestion-card--active" : ""}`}
            onClick={() => onSelect(preset)}
          >
            <span className="prompt-suggestion-text">{preset.label}</span>
            {preset.description && (
              <span className="prompt-suggestion-desc">{preset.description}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export default DemoPresetPanel;
