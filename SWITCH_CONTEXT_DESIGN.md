# Switch Context — Design Document

> Rama: `feat/switch-context`
> Fecha: 2026-03-17

---

## 1. Motivación

Harvey (H.A.R.V.E.Y.) recibía en cada llamada un prompt de planning que describía **todas** las herramientas disponibles:

- **5 herramientas SaaS** (`subscriptions`, `optimal`, `summary`, `iPricing`, `validate`)
- **9 herramientas API** (`min_time`, `capacity_at`, `capacity_during`, `quota_exhaustion_threshold`, `rates`, `quotas`, `limits`, `idle_time_period`, `evaluate_api_datasheet`)

Esto presentaba dos problemas claros:

1. **Latencia / coste**: un prompt más grande → más tokens → más tiempo y coste por llamada al LLM.
2. **Ruido cognitivo**: Harvey razonaba sobre herramientas irrelevantes para la pregunta. Con preguntas puramente API no necesita saber nada de Pricing2Yaml, y viceversa.

A medida que el sistema escale con más tools, el problema empeora de forma lineal.

---

## 2. Solución implementada: Opción B (prompts separados + hard enforcement)

### 2.1 Niveles de enforcement

| Nivel | Mecanismo | Descripción |
|-------|-----------|-------------|
| **Soft** (prompt) | `SAAS_PLAN_PROMPT` / `API_PLAN_PROMPT` | Harvey solo ve las herramientas de su modo. No puede planificar lo que no conoce. |
| **Hard** (ejecución) | `_execute_actions()` en `agent.py` | Si a pesar de todo el LLM generara una acción del modo contrario, se lanza `ValueError` antes de llamar al MCP. |
| **Silent drop** (parsing) | `_normalize_actions()` + `_parse_action_entry()` | Las acciones con nombre fuera del `allowed_actions` del modo se descartan silenciosamente en la fase de normalización del plan. |

### 2.2 Archivos modificados

```
harvey_api/src/harvey_api/agent.py       ← núcleo: prompts, routing, enforcement
harvey_api/src/harvey_api/app.py         ← endpoint /chat: nuevo campo mode
frontend/src/types.ts                    ← tipo ContextMode + ChatRequest.mode
frontend/src/App.tsx                     ← estado mode, localStorage, botón toggle,
                                            supresión de URLs en modo API
frontend/src/components/ControlPanel.tsx ← secciones condicionales por modo
frontend/src/components/ContextManager.tsx ← título y URL input condicionales
frontend/src/styles.css                  ← estilos del botón .mode-toggle
```

### 2.3 Nuevas constantes en `agent.py`

```python
# Tipo literal para el modo
ContextMode = Literal["saas", "api", "all"]

# Mapa modo → conjunto de acciones permitidas
ALLOWED_ACTIONS_BY_MODE: Dict[str, Set[str]] = {
    "saas": PRICING_ACTIONS,   # {"optimal", "subscriptions", "summary", "iPricing", "validate"}
    "api":  API_ACTIONS,       # {"min_time", "capacity_at", ..., "evaluate_api_datasheet"}
    "all":  ALLOWED_ACTIONS,   # unión de los dos
}

SAAS_PLAN_PROMPT  # DEFAULT_PLAN_PROMPT sin la sección de API tools
API_PLAN_PROMPT   # Prompt compacto centrado en rate/quota analysis
```

---

## 3. Flujo del dato — antes vs. después

### ANTES (modo único, siempre "all")

```
Frontend → POST /chat { question, pricing_url?, pricing_yaml? }
    ↓
HarveyAgent.handle_question()
    ↓ DEFAULT_PLAN_PROMPT (todas las tools descritas)
    ↓ LLM genera plan (puede usar cualquier herramienta)
    ↓ _normalize_actions()  ← valida contra ALLOWED_ACTIONS
    ↓ _execute_actions()    ← llama MCP para cada acción
    ↓
MCPWorkflowClient → MCP Server → (Analysis API / Prime4API / A-MINT)
```

### DESPUÉS (switch context)

```
Frontend → POST /chat { question, pricing_url?, pricing_yaml?, mode: "saas"|"api"|"all" }
    ↓
HarveyAgent.handle_question(mode)
    ↓ allowed_actions = ALLOWED_ACTIONS_BY_MODE[mode]
    ↓
    ├─ mode="saas" → SAAS_PLAN_PROMPT (~115 líneas, sin API tools)
    ├─ mode="api"  → API_PLAN_PROMPT  (~80 líneas, sin SaaS tools)
    └─ mode="all"  → DEFAULT_PLAN_PROMPT (comportamiento original)
    ↓
    ↓ LLM genera plan
    ↓ _normalize_actions(allowed_actions)  ← silently drops acciones fuera del modo
    ↓ _execute_actions(allowed_actions)    ← hard-reject si algo se cuela
    ↓
MCPWorkflowClient → MCP Server → solo los endpoints relevantes
```

**Impacto en tokens por petición (aproximado):**

| Modo | Tokens del prompt de planning | Reducción |
|------|-------------------------------|-----------|
| `all` | ~1.200 | 0 % (baseline) |
| `saas` | ~750 | ~37 % menos |
| `api` | ~600 | ~50 % menos |

---

## 4. Ventajas respecto al diseño anterior

| # | Ventaja | Detalle |
|---|---------|---------|
| 1 | **Menos latencia** | El LLM procesa un contexto más pequeño → menos tiempo de inferencia, especialmente con modelos de razonamiento alto (`reasoning_effort="high"`). |
| 2 | **Menos coste** | Menos tokens de entrada y de razonamiento en cada llamada. |
| 3 | **Menor riesgo de alucinación cross-mode** | Harvey no "ve" las herramientas del otro modo, por lo que es mucho menos probable que las planifique erróneamente. |
| 4 | **Enforcement real** | Incluso si el LLM se equivocara (poco probable dado el punto anterior), la capa de ejecución lo bloquea. No es solo "soft guidance". |
| 5 | **UX explícita** | El usuario sabe en qué modo está. El botón en el header persiste entre sesiones via `localStorage`. |
| 6 | **Deuda técnica mínima** | No hay nuevos servicios, no hay cambios en el MCP server ni en Docker Compose. Los sets `PRICING_ACTIONS` / `API_ACTIONS` ya existían. |
| 7 | **Backward-compatible** | `mode` tiene default `"all"` → cualquier cliente que no lo envíe obtiene el comportamiento original. |

---

## 5. Desventajas / trade-offs

| # | Desventaja | Impacto / Mitigación |
|---|------------|----------------------|
| 1 | **Duplicación de texto en prompts** | `SAAS_PLAN_PROMPT` y `DEFAULT_PLAN_PROMPT` comparten ~85 % del texto. Si se actualiza la descripción de una herramienta SaaS hay que actualizarlo en dos sitios. **Mitigación**: los prompts son estables; los cambios son infrecuentes. A futuro, se pueden extraer sub-cadenas reutilizables. |
| 2 | **El usuario debe saber qué modo usar** | Si el usuario está en modo `saas` y pregunta por rate limits, Harvey no tendrá herramientas para responder. **Mitigación**: modo `all` como default; la UI muestra claramente el modo activo. |
| 3 | **Estado de modo no vinculado al contexto** | Un usuario puede tener un YAML de SaaS cargado y cambiar a modo API por error. Harvey no advertirá de ello (simplemente ignorará el YAML). **Mitigación**: esto es un escenario de uso incorrecto, no un bug. |
| 4 | **No se propaga en el historial de chat** | Si el usuario cambia de modo a mitad de una conversación, las respuestas anteriores del historial pueden haber usado un modo diferente. No hay confusión técnica (cada request es independiente), pero puede ser conceptualmente confuso. |

---

## 6. Posibles mejoras futuras

- Inferencia automática del modo basada en el contenido del contexto (si hay YAML Pricing2Yaml → SaaS; si hay Datasheet YAML → API).
- Mostrar en el transcript de chat el modo que se usó para cada respuesta.
- Extraer los bloques de texto de los prompts a sub-constantes para evitar la duplicación.
- Añadir un cuarto modo `"api+saas"` que habilite ambos pero con mayor prioridad para uno de ellos.
