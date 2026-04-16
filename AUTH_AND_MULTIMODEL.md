# Autenticación y soporte multi-modelo en H.A.R.V.E.Y.

Este documento describe la integración de autenticación HTTP Basic y soporte para múltiples proveedores LLM (OpenAI y Google Gemini) añadida al proyecto.

---

## Motivación

El sistema se usa en un contexto académico con un administrador y varios grupos de alumnos. El administrador usa la clave configurada en el entorno y los alumnos aportan su propia API key de Gemini, sin acceso a la clave del servidor.

---

## Arquitectura de la solución

### Autenticación: HTTP Basic Auth

Se eligió **HTTP Basic Auth** sobre JWT por varias razones:

- **Cero dependencias nuevas** — usa `fastapi.security.HTTPBasic` (built-in de FastAPI) y `secrets.compare_digest` (stdlib de Python).
- **Sin estado en el servidor** — no hay tokens que gestionar, renovar ni invalidar.
- **Soporte nativo para cuentas compartidas** — varios alumnos pueden usar las mismas credenciales simultáneamente sin conflictos.
- **Adecuado para la escala del proyecto** — 6 usuarios fijos sin base de datos.

Las credenciales viven en `harvey_api/users.json`, separado del código Python. Añadir un usuario es editar ese fichero y reiniciar el servidor.

### Soporte multi-modelo: OpenAI-compatible API de Gemini

Google expone una API compatible con el SDK de OpenAI en `https://generativelanguage.googleapis.com/v1beta/openai/`. Esto significa que el cliente `OpenAI` del SDK oficial funciona con Gemini cambiando únicamente el `base_url` y la `api_key`. **No se instala ninguna librería adicional de Gemini.**

---

## Ficheros creados o modificados

### Backend (`harvey_api/`)

| Fichero | Cambio |
|---|---|
| `users.json` | **Nuevo.** Credenciales de los 6 usuarios en texto plano. |
| `src/harvey_api/auth.py` | **Nuevo.** Lógica de autenticación HTTP Basic. |
| `src/harvey_api/config.py` | Añadido campo `gemini_model` (por defecto `gemini-2.0-flash`). |
| `src/harvey_api/llm_client.py` | Añadido campo `base_url` a `OpenAIClientConfig` y pasado al constructor de `OpenAI`. |
| `src/harvey_api/agent.py` | Añadido `_resolve_llm()` y parámetros `api_key`/`provider` en `handle_question`, `_generate_plan` y `_generate_answer`. |
| `src/harvey_api/app.py` | Protección de rutas `/chat`, `/upload`, `/delete`. Nuevos campos en `ChatRequest`. Endpoint `GET /auth/me`. Handler global de excepciones para CORS. |

### Frontend (`frontend/`)

| Fichero | Cambio |
|---|---|
| `src/context/authContext.tsx` | **Nuevo.** Estado global de autenticación (usuario, rol, credenciales, api_key, proveedor). |
| `src/components/LoginPage.tsx` | **Nuevo.** Pantalla de login con usuario y contraseña. |
| `src/components/ApiKeySetup.tsx` | **Nuevo.** Pantalla de configuración de API key para alumnos (solo Gemini + input de key). |
| `src/types.ts` | Añadido `api_key` a `ChatRequest`. |
| `src/utils.ts` | Todas las funciones de fetch (`chatWithAgent`, `uploadYamlPricing`, `deleteYamlPricing`) reciben `credentials` y lo envían como `Authorization: Basic <credentials>`. |
| `src/App.tsx` | Integración de `useAuth`, renderizado condicional (login → api key setup → chat), credenciales y api_key en todos los requests, botón de logout en cabecera. |
| `src/main.tsx` | Envuelto en `<AuthProvider>`. |

---

## Flujo completo de uso

```
1. El usuario abre la app → aparece la pantalla de login.

2. Introduce usuario y contraseña.
   El frontend llama a GET /auth/me con Authorization: Basic <base64(user:pass)>.
   - 401 → "Credenciales incorrectas"
   - 200 → guarda username, role y credentials en el estado global.

3a. Si role === "admin":
    Va directamente al chat. Todas las peticiones usan la clave configurada en HARVEY_LLM_KEY.

3b. Si role === "student":
    Aparece la pantalla de API key.
    El alumno pega su API key de Gemini.
    Al confirmar → pasa al chat.

4. En el chat, cada petición lleva:
   - Header Authorization: Basic <credentials>
   - Body: { ..., api_key: "<key_del_alumno>" }  (solo students)

5. El backend:
   - Valida las credenciales con HTTP Basic.
   - Si role === "student" y api_key está vacía → 400.
   - Si role === "admin" → usa la clave del .env, ignora api_key del body.
   - Si role === "student" → crea un OpenAIClient temporal con la key y el base_url del proveedor.

6. El alumno puede cerrar sesión con el botón "Log out".
```

---

## Credenciales de acceso

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `HarveyAdmin2024` | Admin — usa la API key del `.env` |
| `grupo1` | `Grupo1Harvey24` | Alumno — pega su propia key |
| `grupo2` | `Grupo2Harvey24` | Alumno |
| `grupo3` | `Grupo3Harvey24` | Alumno |
| `grupo4` | `Grupo4Harvey24` | Alumno |
| `grupo5` | `Grupo5Harvey24` | Alumno |

Para añadir o modificar usuarios: editar `harvey_api/users.json` y reiniciar el servidor.

---

## Rutas protegidas

| Endpoint | Método | Requiere auth |
|---|---|---|
| `GET /health` | Público | No |
| `GET /events` | Público | No (SSE no soporta cabeceras custom en el browser) |
| `GET /auth/me` | Auth | Sí — devuelve `{ username, role }` |
| `POST /chat` | Auth | Sí — student además necesita `api_key` en el body |
| `POST /upload` | Auth | Sí |
| `DELETE /pricing/{filename}` | Auth | Sí |

---

## Soporte de proveedores LLM

| Proveedor | SDK usado | Base URL | Cómo obtener la key |
|---|---|---|---|
| OpenAI | `openai` | Por defecto (`api.openai.com`) | [platform.openai.com](https://platform.openai.com) |
| Google Gemini | `openai` (compatible) | `https://generativelanguage.googleapis.com/v1beta/openai/` | [aistudio.google.com](https://aistudio.google.com) |

El modelo de Gemini por defecto es `gemini-2.0-flash`. Se puede cambiar con la variable de entorno `GEMINI_MODEL`.

---

## Decisiones de diseño relevantes

**¿Por qué no JWT?**
JWT añade complejidad (expiración, refresh tokens, librería extra) sin aportar valor para un sistema con 6 usuarios fijos y sin base de datos. HTTP Basic Auth es suficiente y más simple.

**¿Por qué `users.json` y no hardcodeado?**
Separar las credenciales del código permite añadir o cambiar usuarios editando un fichero JSON sin tocar Python ni hacer un nuevo deploy.

**¿Por qué no se protege `/events`?**
El endpoint SSE usa la API `EventSource` del browser, que no soporta cabeceras HTTP custom. Protegerlo requeriría un mecanismo distinto (token en query param). El endpoint no expone datos sensibles, solo notificaciones de transformación de URLs.

**¿Por qué cliente LLM temporal por request?**
El `HarveyAgent` es un singleton. Para no bloquear concurrencia ni hacer al agente stateful, cada request con `api_key` crea un `OpenAIClient` ligero que se descarta al terminar. El cliente global del admin sigue siendo el singleton.
