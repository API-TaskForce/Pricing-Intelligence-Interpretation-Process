import { useState, useEffect } from "react";
import { ThemeContext, ThemeType } from "../context/themeContext";

export interface PlaygroundQuestion {
  id: string;
  icon: string;
  label: string;
  description?: string;
  response: string;
  charts?: { label: string; url: string }[];
  sectionStart?: string;
}

export interface ApiScenario {
  id: string;
  name: string;
  icon: string;
  questions: PlaygroundQuestion[];
}

// ── Ground truth scenarios ─────────────────────────────────────────────────
// Fill in `response` with values from Bruno after running against prime4api.

const DISCLAIMER = `⚠️  Nota: todos los resultados asumen CRF = 1 (1 email por petición) y concurrencia = 1.`;

const SENDGRID_2025_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "min-time-50k",
    sectionStart: "🔍 Propósito general",
    icon: "⏱",
    label: "¿Cuánto tiempo necesito para enviar 50.000 emails?",
    description: "",
    response:
      `Tiempo mínimo para enviar 50.000 emails (capacity_goal = 50.000)
Endpoint: /mail/send

  Plan Free   →  999 días y 5 segundos
  Plan Pro    →  30 días, 16 min y 40 s
  Plan Ultra  →  1 h, 23 min y 20 s
  Plan Mega   →  16 min y 40 s

${DISCLAIMER}`,
    charts: [
      { label: "Free", url: "/single-free-50k.html" },
      { label: "Pro", url: "/single-pro-50k.html" },
      { label: "Ultra", url: "/single-ultra-50k.html" },
      { label: "Mega", url: "/single-mega-50k.html" },
    ],
  },
  {
    id: "max-speed-exhaustion",
    icon: "⚡",
    label: "¿A qué velocidad máxima puedo enviar peticiones y durante cuánto tiempo?",
    description: "",
    charts: [
      { label: "Free", url: "/exhaustions/free.html" },
      { label: "Pro", url: "/exhaustions/pro.html" },
      { label: "Ultra", url: "/exhaustions/ultra.html" },
      { label: "Mega", url: "/exhaustions/mega.html" },
    ],
    response:
      `Velocidad máxima de envío y tiempo hasta agotar la cuota
Endpoint: /mail/send

Velocidad máxima (rate limit):
  Plan Free   →  10 req/s  (= 10 emails/s con CRF = 1)
  Plan Pro    →  10 req/s  (= 10 emails/s con CRF = 1)
  Plan Ultra  →  10 req/s  (= 10 emails/s con CRF = 1)
  Plan Mega   →  50 req/s  (= 50 emails/s con CRF = 1)

Tiempo hasta agotar la cuota a máxima velocidad (CRF = 1):
  Plan Free   →  5 s               (cuota: 50 emails / día)
  Plan Pro    →  1 h 6 min 40 s   (cuota: 40.000 emails / 30 días)
  Plan Ultra  →  2 h 46 min 40 s  (cuota: 100.000 emails / 30 días)
  Plan Mega   →  1 h 40 min        (cuota: 300.000 emails / 30 días)

${DISCLAIMER}`,
  },

  {
    id: "supports-demand-over-time",
    icon: "📈",
    label: "¿Puedo enviar 10 peticiones por segundo (10RPS) y 2000 peticiones al día (RPD)?",
    description: "",
    charts: [
      { label: "Comprueba la demanda", url: "/demands-ground-truth.html" }
    ],
    response:
      `¿Puedo enviar 10 peticiones por segundo (10RPS) y 2000 peticiones al día (RPD)?
Endpoint: /mail/send

Análisis de la demanda en un periodo de 1 mes:

  Plan Free   →  ❌ NO (quota_exceeded)
                 Límite del plan: 50
                 En un mes consumiríamos 60.000 emails, pero solo podríamos enviar 50, habría que hacer upgrade a uno de los otros 3 planes.

  Plan Pro    →  ❌ NO (quota_exceeded)
                 Límite del plan: 40.000
                 En un mes consumiríamos 60.000 emails, pero solo podríamos enviar 40.000, habría que hacer upgrade a uno de los dos siguientes planes

  Plan Ultra  →  ✅ SÍ (Soporta la demanda)

  Plan Mega   →  ✅ SÍ (Soporta la demanda)

${DISCLAIMER}`,
  },

  {
    id: "idle-time-period",
    icon: "🔄",
    label: "¿Cuánto tiempo tendré que esperar tras consumir toda mi cuota?",
    description: "",
    response:
      `Tiempo de espera tras agotar la cuota a máxima velocidad (CRF = 1)
Endpoint: /mail/send

  Plan Free   →  23 h 59 min 55 s      (cuota: 50 emails / día)
  Plan Pro    →  29 días 22 h 53 min 20 s  (cuota: 40.000 emails / 30 días)
  Plan Ultra  →  29 días 21 h 13 min 20 s  (cuota: 100.000 emails / 30 días)
  Plan Mega   →  29 días 22 h 20 min        (cuota: 300.000 emails / 30 días)

Ejemplo (Plan Pro): a máxima velocidad la cuota se agota en ~1 h 6 min 40 s.
Si eso ocurre al inicio del ciclo de 30 días, hay que esperar ~29 días y 22 h 53 min
hasta que la cuota se renueve.

${DISCLAIMER}`,
  },
];

const SENDGRID_2025_OPTIMAL_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "optimal-overage-50k",
    sectionStart: "💡 Suscripción óptima",
    icon: "💰",
    label: "¿Cuál es la suscripción óptima para enviar 50.000 correos al mes (overage permitido)?",
    description: "optimal · desired_capacity=50.000 · overage permitido",
    charts: [{ label: "Ver recomendación", url: "/recommendations/first.html" }],
    response:
`Suscripción óptima · 50.000 correos/mes · overage permitido
Endpoint: /mail/send

Resultados ordenados por coste total:
  Plan Pro    →  $19.95/mes  (base $9.95 + overage $10.00)   ✅ más económico
                  Tiempo hasta capacidad: 1 h 23 min 20 s
  Plan Free   →  $49.95/mes  (base $0.00 + overage $49.95)
                  Tiempo hasta capacidad: 1 h 23 min 20 s
  Plan Ultra  →  $79.95/mes  (base $79.95, sin overage)
                  Tiempo hasta capacidad: 1 h 23 min 20 s
  Plan Mega   →  $199.95/mes (base $199.95, sin overage)
                  Tiempo hasta capacidad: 16 min 40 s

→ Si el overage no es un problema, el Plan Pro es el más rentable ($19.95/mes).
  El Plan Mega es 10× más caro pero completa el envío en 16 min 40 s en lugar de 1 h 23 min.

${DISCLAIMER}`,
  },
  {
    id: "optimal-no-overage-50k",
    icon: "🚫",
    label: "¿Y si no quiero incurrir en costes de overage?",
    description: "optimal · desired_capacity=50.000 · sin overage",
    charts: [{ label: "Ver recomendación", url: "/recommendations/second.html" }],
    response:
`Suscripción óptima · 50.000 correos/mes · sin overage
Endpoint: /mail/send

Planes viables (sin coste de overage):
  Plan Ultra  →  $79.95/mes  ✅ más económico sin overage
                  Tiempo hasta capacidad: 1 h 23 min 20 s
  Plan Mega   →  $199.95/mes
                  Tiempo hasta capacidad: 16 min 40 s

Planes no viables (requieren overage para alcanzar 50.000 emails):
  Plan Pro    →  necesita overage ($10.00) → descartado
  Plan Free   →  necesita overage ($49.95) → descartado

→ Si prefieres evitar el overage, el Plan Ultra ($79.95/mes) es la opción más económica.
  Pro y Free no pueden cubrir 50.000 correos con su cuota base mensual.

${DISCLAIMER}`,
  },
  {
    id: "optimal-budget-50k",
    icon: "🏷️",
    label: "¿Y si además tengo un presupuesto máximo de $40/mes?",
    description: "optimal · desired_capacity=50.000 · max_budget=$40",
    charts: [{ label: "Ver recomendación", url: "/recommendations/third.html" }],
    response:
`Suscripción óptima · 50.000 correos/mes · presupuesto máximo $40
Endpoint: /mail/send

Planes dentro del presupuesto (≤ $40):
  Plan Pro    →  $19.95/mes  (base $9.95 + overage $10.00)   ✅ único viable
                  Tiempo hasta capacidad: 1 h 23 min 20 s
                  Margen restante: $20.05

Planes fuera del presupuesto (budget_limit):
  Plan Free   →  $49.95/mes  (overage $49.95)  → supera el límite
  Plan Ultra  →  $79.95/mes                    → supera el límite
  Plan Mega   →  $199.95/mes                   → supera el límite

→ Con presupuesto de $40, el Plan Pro ($19.95 total) es el único viable, con $20.05 de margen.
  El Plan Free parece gratuito pero el overage necesario ($49.95) supera igualmente el límite.

${DISCLAIMER}`,
  },
  {
    id: "optimal-100k",
    icon: "🔀",
    label: "¿Cuál es la mejor suscripción para enviar 100.000 correos al mes?",
    description: "optimal · desired_capacity=100.000",
    charts: [{ label: "Ver recomendación", url: "/recommendations/fourth.html" }],
    response:
`Suscripción óptima · 100.000 correos/mes
Endpoint: /mail/send

Resultados ordenados por coste total:
  Plan Pro    →  $69.95/mes  (base $9.95 + overage $60.00)   ✅ más económico
                  Tiempo hasta capacidad: 2 h 46 min 40 s
  Plan Ultra  →  $79.95/mes  (base $79.95, sin overage)       ← solo $10 más caro
                  Tiempo hasta capacidad: 2 h 46 min 40 s
  Plan Free   →  $99.95/mes  (base $0.00 + overage $99.95)
                  Tiempo hasta capacidad: 2 h 46 min 40 s
  Plan Mega   →  $199.95/mes (base $199.95, sin overage)
                  Tiempo hasta capacidad: 33 min 20 s

→ Sorpresa: aunque Ultra tiene cuota de 100.000 emails, el Plan Pro sale más barato
  ($69.95 vs $79.95) y llega exactamente a la misma velocidad (2 h 46 min 40 s).
  Solo conviene Ultra si se prefiere evitar el overage, la diferencia es solo $10/mes.
  El Mega es casi 3 veces más caro pero finaliza el envío en 33 min 20 s.

${DISCLAIMER}`,
  },
];

const SENDGRID_2026_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "min-time-1000",
    icon: "⏱",
    label: "How much time to send 1,000 requests?",
    description: "min-time · capacity_goal=1000 · datasheet: sendgrid-2026",
    response: "_Pending ground truth — run in Bruno and fill in._",
  },
];

const MAILERSEND_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "min-time-1000",
    icon: "⏱",
    label: "How much time to send 1,000 requests?",
    description: "min-time · capacity_goal=1000 · datasheet: mailersend",
    response: "_Pending ground truth — run in Bruno and fill in._",
  },
];

const PEERTUBE_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "min-time-1000",
    icon: "⏱",
    label: "How much time to send 1,000 requests?",
    description: "min-time · capacity_goal=1000 · datasheet: peertube",
    response: "_Pending ground truth — run in Bruno and fill in._",
  },
];

const DAILYMOTION_QUESTIONS: PlaygroundQuestion[] = [
  {
    id: "min-time-1000",
    icon: "⏱",
    label: "How much time to send 1,000 requests?",
    description: "min-time · capacity_goal=1000 · datasheet: dailymotion",
    response: "_Pending ground truth — run in Bruno and fill in._",
  },
];

export const API_SCENARIOS: ApiScenario[] = [
  { id: "sendgrid-2025", name: "Sendgrid 2025", icon: "📧", questions: [...SENDGRID_2025_QUESTIONS, ...SENDGRID_2025_OPTIMAL_QUESTIONS] },
  { id: "sendgrid-2026", name: "Sendgrid 2026", icon: "📧", questions: SENDGRID_2026_QUESTIONS },
  { id: "mailersend", name: "Mailersend", icon: "✉️", questions: MAILERSEND_QUESTIONS },
  { id: "peertube", name: "PeerTube", icon: "📹", questions: PEERTUBE_QUESTIONS },
  { id: "dailymotion", name: "Dailymotion", icon: "🎬", questions: DAILYMOTION_QUESTIONS },
];

const initTheme = (): ThemeType => {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem("pricing-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

// ── Question card ──────────────────────────────────────────────────────────
function QuestionCard({ question }: { question: PlaygroundQuestion }) {
  const [open, setOpen] = useState(false);
  const [activeChart, setActiveChart] = useState<string | null>(null);

  return (
    <>
      <div className={`p4-question-card${open ? " p4-question-card--expanded" : ""}`}>
        <button
          type="button"
          className="p4-question-header"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className="p4-question-icon">{question.icon}</span>
          <span className="p4-question-meta">
            <span className="p4-question-label">{question.label}</span>
            {question.description && (
              <span className="p4-question-desc">{question.description}</span>
            )}
          </span>
          <span className="p4-question-chevron">{open ? "▲" : "▼"}</span>
        </button>

        {open && (
          <div className="p4-question-body">
            <div className="p4-response">
              <p className="p4-response-title">Ground truth response</p>
              <pre className="p4-response-json">{question.response}</pre>
            </div>
            {question.charts && question.charts.length > 0 && (
              <div className="p4-charts">
                {question.charts.map((chart) => (
                  <button
                    key={chart.url}
                    type="button"
                    className="chart-open-btn"
                    // TO SWITCH TO NEW TAB: replace the onClick below with:
                    // onClick={() => window.open(chart.url, "_blank")}
                    onClick={() => setActiveChart(chart.url)}
                  >
                    📈 {chart.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {activeChart && (
        <div className="chart-modal-overlay" onClick={() => setActiveChart(null)}>
          <div className="chart-modal" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="chart-modal-close"
              onClick={() => setActiveChart(null)}
            >
              ✕
            </button>
            <iframe
              className="chart-modal-iframe"
              src={activeChart}
              title="Chart"
            />
          </div>
        </div>
      )}
    </>
  );
}

// ── Main component ─────────────────────────────────────────────────────────
interface Props {
  onBack: () => void;
}

function Prime4ApiPlayground({ onBack }: Props) {
  const [theme, setTheme] = useState<ThemeType>(initTheme);
  const [activeScenarioId, setActiveScenarioId] = useState(API_SCENARIOS[0].id);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("pricing-theme", theme);
  }, [theme]);

  const scenario = API_SCENARIOS.find((s) => s.id === activeScenarioId) ?? API_SCENARIOS[0];

  return (
    <ThemeContext.Provider value={theme}>
      <div className="app p4-app">
        <header className="header-bar">
          <div>
            <h1>
              PRIME4API <span className="mode-badge">Ground Truth</span>
            </h1>
            <p>Reference responses for validating H.A.R.V.E.Y. answers.</p>
          </div>
          <div className="header-actions">
            <button type="button" className="session-reset" onClick={onBack}>
              ← Back
            </button>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              aria-label="Toggle color theme"
            >
              {theme === "dark" ? "☀️ Switch to light mode" : "🌙 Switch to dark mode"}
            </button>
          </div>
        </header>

        <nav className="mode-nav">
          {API_SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`mode-tab${s.id === activeScenarioId ? " mode-tab--active" : ""}`}
              onClick={() => setActiveScenarioId(s.id)}
            >
              {s.icon} {s.name}
            </button>
          ))}
        </nav>

        <main className="p4-main">
          <section className="p4-questions-section">
            <h2 className="p4-section-title">
              {scenario.icon} {scenario.name}
            </h2>
            <div className="p4-questions-list">
              {scenario.questions.map((q) => (
                <div key={q.id}>
                  {q.sectionStart && (
                    <h3 className="p4-section-heading">{q.sectionStart}</h3>
                  )}
                  <QuestionCard question={q} />
                </div>
              ))}
            </div>
          </section>
        </main>
      </div>
    </ThemeContext.Provider>
  );
}

export default Prime4ApiPlayground;
