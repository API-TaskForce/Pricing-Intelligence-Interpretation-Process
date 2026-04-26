import { FormEvent, useState } from "react";
import type { ClarificationRequest } from "../types";

interface Props {
  clarification: ClarificationRequest;
  onSubmit: (answers: Record<string, string>) => void;
  disabled?: boolean;
}

function ClarificationPanel({ clarification, onSubmit, disabled }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const set = (field: string, value: string) =>
    setAnswers((prev) => ({ ...prev, [field]: value }));

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const filled = Object.fromEntries(
      Object.entries(answers).filter(([, v]) => v.trim() !== "")
    );
    if (Object.keys(filled).length === 0) return;
    onSubmit(filled);
  };

  const isReady = clarification.fields.some((f) => (answers[f] ?? "").trim() !== "");

  return (
    <form className="clarification-panel" onSubmit={handleSubmit}>
      <p className="clarification-panel__hint">
        Rellena los campos que necesita H.A.R.V.E.Y. para continuar:
      </p>
      {clarification.fields.map((field) => (
        <div key={field} className="clarification-field">
          {field === "plan_name" && clarification.availablePlans && clarification.availablePlans.length > 0 ? (
            <label>
              Plan
              <select
                value={answers["plan_name"] ?? ""}
                onChange={(e) => set("plan_name", e.target.value)}
                disabled={disabled}
              >
                <option value="">— Elige un plan —</option>
                {clarification.availablePlans.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
                <option value="__all__">Todos los planes</option>
              </select>
            </label>
          ) : field === "plan_name" ? (
            <label>
              Plan
              <input
                type="text"
                placeholder="Nombre del plan (ej. pro)"
                value={answers["plan_name"] ?? ""}
                onChange={(e) => set("plan_name", e.target.value)}
                disabled={disabled}
              />
            </label>
          ) : field === "capacity_request_factor" ? (
            <label>
              Unidades por llamada API
              <input
                type="number"
                min={1}
                placeholder="Ej. 500"
                value={answers["capacity_request_factor"] ?? ""}
                onChange={(e) => set("capacity_request_factor", e.target.value)}
                disabled={disabled}
              />
              {clarification.crfRanges && (
                <span className="clarification-field__hint">
                  Rango: {clarification.crfRanges.min ?? "?"} – {clarification.crfRanges.max ?? "?"}
                </span>
              )}
            </label>
          ) : field === "endpoint_path" && clarification.availableEndpoints && clarification.availableEndpoints.length > 1 ? (
            <label>
              Endpoint
              <select
                value={answers["endpoint_path"] ?? ""}
                onChange={(e) => set("endpoint_path", e.target.value)}
                disabled={disabled}
              >
                <option value="">— Elige un endpoint —</option>
                {clarification.availableEndpoints.map((ep) => (
                  <option key={ep} value={ep}>{ep}</option>
                ))}
              </select>
            </label>
          ) : field === "endpoint_path" ? (
            <label>
              Endpoint
              <input
                type="text"
                placeholder="Ej. /mail/send"
                value={answers["endpoint_path"] ?? ""}
                onChange={(e) => set("endpoint_path", e.target.value)}
                disabled={disabled}
              />
            </label>
          ) : field === "alias" && clarification.availableAliases && clarification.availableAliases.length > 1 ? (
            <label>
              Alias / función
              <select
                value={answers["alias"] ?? ""}
                onChange={(e) => set("alias", e.target.value)}
                disabled={disabled}
              >
                <option value="">— Elige un alias —</option>
                {clarification.availableAliases.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </label>
          ) : field === "alias" ? (
            <label>
              Alias / función
              <input
                type="text"
                placeholder="Nombre del alias"
                value={answers["alias"] ?? ""}
                onChange={(e) => set("alias", e.target.value)}
                disabled={disabled}
              />
            </label>
          ) : field === "capacity_unit" && clarification.availableCapacityUnits && clarification.availableCapacityUnits.length > 1 ? (
            <label>
              Unidad de capacidad
              <select
                value={answers["capacity_unit"] ?? ""}
                onChange={(e) => set("capacity_unit", e.target.value)}
                disabled={disabled}
              >
                <option value="">— Elige una unidad —</option>
                {clarification.availableCapacityUnits.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </label>
          ) : field === "capacity_unit" ? (
            <label>
              Unidad de capacidad
              <input
                type="text"
                placeholder="Ej. emails"
                value={answers["capacity_unit"] ?? ""}
                onChange={(e) => set("capacity_unit", e.target.value)}
                disabled={disabled}
              />
            </label>
          ) : null}
        </div>
      ))}
      <button type="submit" disabled={disabled || !isReady} className="clarification-panel__submit">
        Enviar
      </button>
    </form>
  );
}

export default ClarificationPanel;
