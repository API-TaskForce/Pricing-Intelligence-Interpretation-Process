import { FormEvent, useEffect, useState } from "react";

import ChatTranscript from "./components/ChatTranscript";
import ControlPanel from "./components/ControlPanel";
import ClarificationPanel from "./components/ClarificationPanel";
import DemoPresetPanel from "./components/DemoPresetPanel";
import LoginPage from "./components/LoginPage";
import ApiKeySetup from "./components/ApiKeySetup";
import ModeNav, { MODES } from "./components/ModeNav";
import ModeSettingsButton from "./components/ModeSettingsButton";
import type {
  ChatMessage,
  ChartHtmlEntry,
  ClarificationRequest,
  DatasheetContextItem,
  HarveyMode,
  PromptPreset,
  ContextInputType,
  ChatRequest,
} from "./types";
import { useAppMode } from "./context/appModeContext";
import { SENDGRID_PRESETS, SENDGRID_DEMO_PRESETS } from "./prompts";
import { ThemeContext, ThemeType } from "./context/themeContext";
import {
  chatWithAgent,
  buildChatPayload,
  deleteDatasheet,
  uploadDatasheet,
} from "./utils";
import { PricingContext } from "./context/pricingContext";
import { useAuth } from "./context/authContext";
import {
  MAILERSEND_URL,
  PEERTUBE_URL,
  DAILYMOTION_URL,
  SENDGRID_2025_URL,
  SENDGRID_2026_URL,
} from "./datasheets";

const MODE_DATASHEET: Record<HarveyMode, { label: string; url: string }> = {
  "sendgrid-2025": { label: "Sendgrid@RAPIDAPI_datasheet-2025.yaml", url: SENDGRID_2025_URL },
  "sendgrid-2026": { label: "Sendgrid@RAPIDAPI_datasheet-2026.yaml", url: SENDGRID_2026_URL },
  mailersend: { label: "mailersend_v03.yaml", url: MAILERSEND_URL },
  peertube: { label: "peertube_v03.yaml", url: PEERTUBE_URL },
  dailymotion: { label: "dailymotion_v03.yaml", url: DAILYMOTION_URL },
};

const MODE_PRESETS: Partial<Record<HarveyMode, PromptPreset[]>> = {
  "sendgrid-2025": SENDGRID_PRESETS,
  "sendgrid-2026": SENDGRID_PRESETS,
};

const MODE_DEMO_PRESETS: Partial<Record<HarveyMode, PromptPreset[]>> = {
  "sendgrid-2025": SENDGRID_DEMO_PRESETS,
  "sendgrid-2026": SENDGRID_DEMO_PRESETS,
};

const DEFAULT_MODE: HarveyMode = "sendgrid-2025";

const DEMO_FALLBACK_RESPONSE =
  "Esta es una respuesta de demostración. Inicia sesión para obtener respuestas en tiempo real del agente H.A.R.V.E.Y.";

const initTheme = (): ThemeType => {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("pricing-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

interface AppContentProps {
  isDemo: boolean;
  onLoginClick: () => void;
}

function extractClarificationFromResult(
  fields: string[],
  result: Record<string, unknown>
): ClarificationRequest {
  const steps = Array.isArray((result as any).steps)
    ? (result as any).steps
    : result.action
    ? [result]
    : [];

  const allPayloads: unknown[] = steps.length
    ? steps.map((s: any) => s.payload)
    : [result];

  let availablePlans: string[] | undefined;
  let availableEndpoints: string[] | undefined;
  let availableCapacityUnits: string[] | undefined;
  let availableAliases: string[] | undefined;
  let crfRanges: { min?: number; max?: number } | undefined;

  for (const payload of allPayloads) {
    if (!payload || typeof payload !== "object") continue;
    const p = payload as Record<string, unknown>;
    if (Array.isArray(p.plans) && p.plans.every((x: unknown) => typeof x === "string")) {
      availablePlans = p.plans as string[];
    }
    if (Array.isArray(p.endpoints) && p.endpoints.every((x: unknown) => typeof x === "string")) {
      availableEndpoints = p.endpoints as string[];
    }
    if (Array.isArray(p.capacity_units) && p.capacity_units.every((x: unknown) => typeof x === "string")) {
      availableCapacityUnits = p.capacity_units as string[];
    }
    if (Array.isArray(p.aliases) && p.aliases.every((x: unknown) => typeof x === "string")) {
      availableAliases = p.aliases as string[];
    }
    if (typeof p.min_crf === "number" || typeof p.max_crf === "number") {
      crfRanges = {
        min: typeof p.min_crf === "number" ? p.min_crf : undefined,
        max: typeof p.max_crf === "number" ? p.max_crf : undefined,
      };
    }
  }

  // Filter out fields that are trivially resolved (only 1 option available)
  const filteredFields = fields.filter((field) => {
    if (field === "endpoint_path" && availableEndpoints !== undefined && availableEndpoints.length <= 1) return false;
    if (field === "capacity_unit" && availableCapacityUnits !== undefined && availableCapacityUnits.length <= 1) return false;
    if (field === "alias" && availableAliases !== undefined && availableAliases.length <= 1) return false;
    return true;
  });

  return {
    fields: filteredFields,
    availablePlans,
    availableEndpoints: availableEndpoints && availableEndpoints.length > 1 ? availableEndpoints : undefined,
    availableCapacityUnits: availableCapacityUnits && availableCapacityUnits.length > 1 ? availableCapacityUnits : undefined,
    availableAliases: availableAliases && availableAliases.length > 1 ? availableAliases : undefined,
    crfRanges,
  };
}

function buildClarificationAnswer(answers: Record<string, string>): string {
  const parts: string[] = [];
  if (answers.plan_name === "__all__") parts.push("Para todos los planes disponibles");
  else if (answers.plan_name) parts.push(`Plan: ${answers.plan_name}`);
  if (answers.endpoint_path) parts.push(`Endpoint: ${answers.endpoint_path}`);
  if (answers.alias) parts.push(`Alias: ${answers.alias}`);
  if (answers.capacity_unit) parts.push(`Unidad: ${answers.capacity_unit}`);
  if (answers.capacity_request_factor) parts.push(`${answers.capacity_request_factor} unidades por llamada`);
  return parts.join(", ");
}

function AppContent({ isDemo, onLoginClick }: AppContentProps) {
  const { auth, logout } = useAuth();
  const { queryMode } = useAppMode();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [contextItems, setContextItems] = useState<DatasheetContextItem[]>(() => {
    const { label, url } = MODE_DATASHEET[DEFAULT_MODE];
    return [{ id: crypto.randomUUID(), kind: "yaml-url" as const, label, value: url, origin: "preset" as const }];
  });
  const [isLoading, setIsLoading] = useState(false);
  const [theme, setTheme] = useState<ThemeType>(() => initTheme());
  const [activeMode, setActiveMode] = useState<HarveyMode>(DEFAULT_MODE);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [pendingClarification, setPendingClarification] = useState<ClarificationRequest | null>(null);

  // Reset conversation on logout (isDemo flips false → true)
  useEffect(() => {
    if (isDemo) {
      setMessages([]);
      setQuestion("");
      setPendingClarification(null);
      setActiveMode(DEFAULT_MODE);
    }
  }, [isDemo]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("pricing-theme", theme);
    }
  }, [theme]);

  const isSubmitDisabled =
    isLoading || !question.trim() || (auth!.role === "student" && !auth!.apiKey);

  const needsUpload = (item: DatasheetContextItem) =>
    item.kind === "yaml" && (item.origin === "user" || item.origin === "preset");

  const createContextItems = (inputs: ContextInputType[]): DatasheetContextItem[] =>
    inputs
      .map((item) => ({ ...item, value: item.value.trim(), id: crypto.randomUUID() }))
      .filter(
        (item) =>
          !contextItems.some(
            (existing) => existing.kind === item.kind && existing.value === item.value
          )
      );

  const addContextItems = (inputs: ContextInputType[]) => {
    if (inputs.length === 0) return null;
    const newItems = createContextItems(inputs);

    if (!isDemo) {
      const uploadPromises = newItems
        .filter(needsUpload)
        .map((item) => uploadDatasheet(`${item.id}.yaml`, item.value, auth!.credentials));

      if (uploadPromises.length > 0) {
        Promise.all(uploadPromises).catch((err) => console.error("Upload failed", err));
      }
    }

    setContextItems((prev) => [...prev, ...newItems]);
    return newItems;
  };

  const addContextItem = (input: ContextInputType) => {
    addContextItems([input]);
  };

  const removeContextItem = (id: string) => {
    if (!isDemo) {
      const toDelete = contextItems.filter((item) => item.id === id && needsUpload(item));
      toDelete.forEach((item) =>
        deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
      );
    }
    setContextItems((prev) => prev.filter((item) => item.id !== id));
  };

  const clearContext = () => {
    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }
    setContextItems([]);
  };

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  const handleFilesSelected = (files: FileList | null) => {
    if (!files || files.length === 0) return;

    Promise.all(
      Array.from(files).map((file) =>
        file.text().then((content) => ({ name: file.name, content }))
      )
    )
      .then((results) => {
        const inputs: ContextInputType[] = results
          .filter((r) => Boolean(r.content.trim()))
          .map((r) => ({ kind: "yaml", label: r.name, value: r.content, origin: "user" }));

        if (inputs.length > 0) addContextItems(inputs);

        if (inputs.length !== results.length) {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: "One or more uploaded files were empty and were skipped.",
              createdAt: new Date().toISOString(),
            },
          ]);
        }
      })
      .catch(() => {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Could not read the uploaded file. Please try again.",
            createdAt: new Date().toISOString(),
          },
        ]);
      });
  };

  const handlePromptSelect = (preset: PromptPreset) => {
    setQuestion(preset.question);
    if (preset.context.length > 0) {
      addContextItems(
        preset.context.map((entry) => ({
          kind: entry.kind,
          label: entry.label,
          value: entry.value,
          origin: "preset",
        }))
      );
    }
  };

  const buildModeContextItem = (mode: Exclude<HarveyMode, "general">): DatasheetContextItem => {
    const { label, url } = MODE_DATASHEET[mode];
    return {
      id: crypto.randomUUID(),
      kind: "yaml-url",
      label,
      value: url,
      origin: "preset",
    };
  };

  const handleModeChange = (mode: HarveyMode) => {
    if (mode === activeMode) return;

    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }

    setMessages([]);
    setQuestion("");
    setActiveMode(mode);
    setActivePresetId(null);
    setPendingClarification(null);
    setContextItems([buildModeContextItem(mode)]);
  };

  const handleNewConversation = () => {
    setMessages([]);
    setQuestion("");
    setActivePresetId(null);
    setIsLoading(false);
    setPendingClarification(null);

    if (!isDemo) {
      contextItems
        .filter(needsUpload)
        .forEach((item) =>
          deleteDatasheet(`${item.id}.yaml`, auth!.credentials).catch(() => {})
        );
    }
    setContextItems((prev) => prev.filter((item) => item.kind === "yaml-url"));
  };

  const handleDemoPresetClick = async (preset: PromptPreset) => {
    setActivePresetId(preset.id);
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: preset.question,
      createdAt: new Date().toISOString(),
    };

    let chartHtml: string | undefined;
    let chartHtmlEntries: ChartHtmlEntry[] | undefined;

    if (preset.demoChartUrls && preset.demoChartUrls.length > 0) {
      const results = await Promise.allSettled(
        preset.demoChartUrls.map(async ({ url, label }) => {
          const res = await fetch(url);
          const html = await res.text();
          return { html, label };
        })
      );
      const fulfilled = results
        .filter((r): r is PromiseFulfilledResult<ChartHtmlEntry> => r.status === "fulfilled")
        .map((r) => r.value);
      if (fulfilled.length > 0) chartHtmlEntries = fulfilled;
    } else if (preset.demoChartUrl) {
      try {
        const res = await fetch(preset.demoChartUrl);
        chartHtml = await res.text();
      } catch {
        // show without chart if fetch fails
      }
    }

    const assistantMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: preset.demoResponse ?? DEMO_FALLBACK_RESPONSE,
      createdAt: new Date().toISOString(),
      chartHtml,
      chartHtmlEntries,
    };
    setMessages([userMessage, assistantMessage]);
  };

  const submitQuestion = async (trimmedQuestion: string, currentMessages: ChatMessage[]) => {
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmedQuestion,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setPendingClarification(null);
    setQuestion("");
    setIsLoading(true);

    try {
      const requestBody: ChatRequest = {
        question: trimmedQuestion,
        history: currentMessages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        ...(auth!.role === "student" && { api_key: auth!.apiKey }),
        ...buildChatPayload(contextItems),
        query_mode: queryMode,
      };
      const data = await chatWithAgent(requestBody, auth!.credentials);

      const chartHtml: string | undefined =
        typeof data?.result?.payload?.html === "string"
          ? data.result.payload.html
          : undefined;

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.answer ?? "No response available.",
        createdAt: new Date().toISOString(),
        chartHtml,
        metadata: {
          plan: data.plan ?? undefined,
          result: data.result ?? undefined,
        },
      };
      setMessages((prev) => [...prev, assistantMessage]);

      if (
        queryMode === "guided" &&
        data.plan?.response_mode === "clarify" &&
        Array.isArray(data.plan?.clarification_fields) &&
        data.plan.clarification_fields.length > 0
      ) {
        setPendingClarification(
          extractClarificationFromResult(data.plan.clarification_fields, data.result ?? {})
        );
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Error: ${(error as Error).message}`,
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSubmitDisabled) return;
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) return;
    await submitQuestion(trimmedQuestion, messages);
  };

  const handleClarificationSubmit = async (answers: Record<string, string>) => {
    const answer = buildClarificationAnswer(answers);
    if (!answer) return;
    await submitQuestion(answer, messages);
  };

  const modeLabel = MODES.find((m) => m.id === activeMode)?.label ?? "H.A.R.V.E.Y.";

  return (
    <PricingContext.Provider value={contextItems}>
      <ThemeContext.Provider value={theme}>
        <div className="app">
          <header className="header-bar">
            <div>
              <h1>
                H.A.R.V.E.Y. <span className="mode-badge">{modeLabel}</span>
              </h1>
              <p>Analysing the {modeLabel} API — datasheet pre-loaded and locked.</p>
            </div>
            <div className="header-actions">
              {isDemo ? (
                <>
                  <span className="demo-badge">DEMO</span>
                  <button
                    type="button"
                    className="login-cta"
                    onClick={onLoginClick}
                  >
                    Log in
                  </button>
                </>
              ) : (
                <>
                  <span className="header-user">
                    {auth!.username}
                    {auth!.role === "student" && " · GEMINI"}
                  </span>
                  <ModeSettingsButton />
                  <button
                    type="button"
                    className="session-reset"
                    onClick={handleNewConversation}
                    disabled={isLoading}
                  >
                    New conversation
                  </button>
                  <button
                    type="button"
                    className="session-reset"
                    onClick={logout}
                    disabled={isLoading}
                  >
                    Log out
                  </button>
                </>
              )}
              <button
                type="button"
                className="theme-toggle"
                onClick={toggleTheme}
                aria-label="Toggle color theme"
              >
                {theme === "dark" ? "☀️ Switch to light mode" : "🌙 Switch to dark mode"}
              </button>
            </div>
          </header>

          {isDemo && (
            <div className="demo-banner">
              <span>
                <strong>Demo mode</strong> — Select a preset question to explore H.A.R.V.E.Y.
                Answers are illustrative. Log in to get real-time AI responses.
              </span>
              <button type="button" className="demo-banner-login" onClick={onLoginClick}>
                Log in →
              </button>
            </div>
          )}

          {!isDemo && (
            <ModeNav
              activeMode={activeMode}
              onModeChange={handleModeChange}
              disabled={isLoading}
            />
          )}

          <main className={isDemo && messages.length === 0 ? "main--demo-welcome" : ""}>
            <section className="chat-panel">
              <ChatTranscript
                messages={messages}
                isLoading={isLoading}
                promptPresets={(isDemo ? MODE_DEMO_PRESETS : MODE_PRESETS)[activeMode as HarveyMode] ?? []}
                onPresetSelect={isDemo ? handleDemoPresetClick : handlePromptSelect}
                isDemo={isDemo}
              />
            </section>
            {(!isDemo || messages.length > 0) && (
              <section className="control-panel">
                {isDemo ? (
                  <DemoPresetPanel
                    presets={MODE_DEMO_PRESETS[activeMode as HarveyMode] ?? []}
                    activePresetId={activePresetId}
                    onSelect={handleDemoPresetClick}
                  />
                ) : pendingClarification !== null && queryMode === "guided" ? (
                  <ClarificationPanel
                    clarification={pendingClarification}
                    onSubmit={handleClarificationSubmit}
                    disabled={isLoading}
                  />
                ) : (
                  <ControlPanel
                    question={question}
                    contextItems={contextItems}
                    isSubmitting={isLoading}
                    isSubmitDisabled={isSubmitDisabled}
                    lockContext
                    onQuestionChange={setQuestion}
                    onSubmit={handleSubmit}
                    onFileSelect={handleFilesSelected}
                    onContextAdd={addContextItem}
                    onContextRemove={removeContextItem}
                    onContextClear={clearContext}
                  />
                )}
              </section>
            )}
          </main>
        </div>
      </ThemeContext.Provider>
    </PricingContext.Provider>
  );
}

function App() {
  const { auth } = useAuth();
  const [showLogin, setShowLogin] = useState(false);

  // Hide login page automatically after successful login
  useEffect(() => {
    if (auth) setShowLogin(false);
  }, [auth]);

  if (showLogin && !auth) return <LoginPage onBack={() => setShowLogin(false)} />;
  if (auth?.role === "student" && !auth.apiKey) return <ApiKeySetup />;

  return <AppContent isDemo={!auth} onLoginClick={() => setShowLogin(true)} />;
}

export default App;
