import { ChangeEvent, FormEvent, useRef } from "react";
import ContextManager from "./ContextManager";
import type { ContextInputType, DatasheetContextItem } from "../types";

interface Props {
  question: string;
  contextItems: DatasheetContextItem[];
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onFileSelect: (files: FileList | null) => void;
  onContextAdd: (input: ContextInputType) => void;
  onContextRemove: (id: string) => void;
  onContextClear: () => void;
}

function ControlPanel({
  question,
  contextItems,
  isSubmitting,
  isSubmitDisabled,
  onQuestionChange,
  onSubmit,
  onFileSelect,
  onContextAdd,
  onContextRemove,
  onContextClear,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <form className="control-form" onSubmit={onSubmit}>
      <label>
        Question
        <textarea
          name="question"
          required
          rows={4}
          value={question}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
            onQuestionChange(event.target.value)
          }
          placeholder="How long to make 500 API calls with 100 req/day limit?"
        />
      </label>

      <ContextManager
        items={contextItems}
        onAdd={onContextAdd}
        onRemove={onContextRemove}
        onClear={onContextClear}
      />

      <h3>Add Datasheet Context</h3>

      <div className="pricing-actions">
        <section className="ipricing-upload">
          <input
            ref={fileRef}
            style={{ display: "none" }}
            type="file"
            accept=".yaml,.yml"
            multiple
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              onFileSelect(event.target.files ?? null)
            }
          />
          <button
            type="button"
            className="ipricing-file-selector"
            onClick={() => fileRef.current?.click()}
          >
            Select files
          </button>
          <h3>Upload Datasheet YAML (optional)</h3>
          <p style={{ margin: "1em auto" }} className="help-text">
            Upload an API Datasheet YAML so H.A.R.V.E.Y. can evaluate rate
            limits and quotas for a specific plan.
          </p>
        </section>
      </div>

      <div className="control-actions">
        <button type="submit" disabled={isSubmitDisabled}>
          {isSubmitting ? "Processing..." : "Ask"}
        </button>
      </div>
    </form>
  );
}

export default ControlPanel;
