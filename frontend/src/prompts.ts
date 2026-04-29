import type { PromptPreset } from './types';

export const SENDGRID_PRESETS: PromptPreset[] = [
  {
    id: 'sg-min-time-30k',
    label: '⏱ 30.000 correos',
    description: '¿Cuánto tardo en enviar 30.000 correos en todos los planes?',
    question: '¿Cuánto tardo en enviar 30.000 correos?',
    context: [],
    demoResponse: `**Plan Free**\n\n- 599 días y 4 segundos\n\n**Plan Pro**\n\n- 49 min 59 s\n\n**Plan Ultra**\n\n- 49 min 59 s\n\n**Plan Mega**\n\n- 9 min 59 s\n\nNotas relevantes:\n\n- El plan Free está limitado por su cuota diaria de 50 emails. Con 30.000 correos esa restricción domina independientemente del CRF.\n- Pro y Ultra tienen el mismo rate limit (10 req/s) y cuota suficiente, por eso sus tiempos coinciden.\n- Mega tiene un rate limit de 50 req/s, cuatro veces superior al resto.`,
  },
  {
    id: 'sg-min-time-1300-pro',
    label: '⏱ 1.300 correos — Pro',
    description: '¿Cuánto tiempo necesito para enviar 1.300 correos en el plan Pro?',
    question: '¿Cuánto tiempo necesito para enviar 1.300 correos en el plan Pro?',
    context: [],
    demoResponse: `**Plan Pro**\n\n- 2 min 9 s\n\nNotas relevantes:\n\n- Con 1.300 correos la cuota mensual del plan Pro (40.000 emails/mes) no es el factor limitante. El cuello de botella es el rate limit de 10 req/s.\n\n**Bloque de simulaciones**\n\n- [Simulación 24 horas](/sendgrid-1300-24h.html)\n- [Simulación 2h](/reduced-sendgrid-1300.html)`,
  },
  {
    id: 'sg-best-plan-1200',
    label: '💡 1.200 correos/día — ¿qué plan?',
    description: '¿Si necesito mandar 1.200 correos en un día, cuál es el plan más barato que me lo permite?',
    question: '¿Si necesito mandar 1.200 correos en un día, cuál es el plan más barato que me lo permite?',
    context: [],
    demoResponse: `**Plan recomendado: Pro**\n\n- Es el plan más barato que permite enviar 1.200 correos en un día.\n- Su cuota de 40.000 correos en 30 días cubre el volumen: 1.200 correos/día es viable mientras el uso mensual se mantenga dentro del tope.\n- Con CRF=1 necesitas 1.200 llamadas al endpoint. Al rate limit de 10 req/s, el envío completo tarda 2 min.\n\nResumen por plan:\n\n- **Free** — No lo permite. Su cuota es de 50 correos/día, insuficiente para 1.200.\n- **Pro** — Sí lo permite. Cuota: 40.000 correos/mes.\n- **Ultra** — Sí lo permite. Cuota: 100.000 correos/mes.\n- **Mega** — Sí lo permite. Cuota: 300.000 correos/mes.\n\nNota: si en algún día superas la media de 1.333 correos/día del plan Pro de forma recurrente, necesitarás subir a Ultra o Mega.`,
  },
  {
    id: 'sg-quota-exhaustion-ultra',
    label: '⚡ Agotar cuota Ultra',
    description: '¿En cuánto tiempo agotaría la cuota mensual del plan Ultra yendo al máximo?',
    question: '¿En cuánto tiempo agotaría la cuota mensual del plan Ultra yendo al máximo de velocidad?',
    context: [],
    demoResponse: `**Plan Ultra**\n\n- Cuota mensual: 100.000 emails en 30 días\n- Tiempo hasta agotar la cuota yendo al máximo: 2 h 46 min 39 s\n\nNotas relevantes:\n\n- El cuello de botella es la cuota mensual de emails, no el rate limit.\n- Una vez agotada la cuota, el plan bloquea el envío hasta el siguiente ciclo de 30 días.`,
  },
  {
    id: 'sg-pro-vs-ultra-50k',
    label: '⚖️ Pro vs Ultra — 50.000 correos',
    description: '¿Qué diferencia hay en tiempo entre el plan Pro y el Ultra para enviar 50.000 correos?',
    question: '¿Qué diferencia hay en tiempo entre el plan Pro y el Ultra para enviar 50.000 correos?',
    context: [],
    demoResponse: `**Plan Pro**\n\n- 30 días 16 min 39 s\n\n**Plan Ultra**\n\n- 1 h 23 min 19 s\n\n**Diferencia**\n\n- Ultra es más rápido por 29 días 22 h 53 min 20 s\n\nNotas relevantes:\n\n- El plan Pro se frena por su cuota de 40.000 emails/mes: con 50.000 correos necesita más de un ciclo mensual.\n- El plan Ultra tiene cuota de 100.000 emails/mes, suficiente para los 50.000 de una sola vez, por lo que el único limitante es el rate limit.`,
  },
];

export const SENDGRID_DEMO_PRESETS: PromptPreset[] = [
  ...SENDGRID_PRESETS,
  {
    id: 'sg-capacity-curve',
    label: '📈 Curva de capacidad',
    description: 'Visualiza la curva de capacidad de todos los planes con CRF entre 1 y 1.000 correos por llamada.',
    question: 'Genera la curva de capacidad de todos los planes con los CRF de la datasheet (1–1.000 correos por llamada).',
    context: [],
    demoResponse: `A continuación puedes ver la curva de capacidad interactiva para todos los planes de Sendgrid.\n\nEl gráfico muestra cómo varía la capacidad acumulada (correos enviables) a lo largo del tiempo según el tamaño de lote por llamada (CRF). Cada línea representa un escenario: el **peor caso** (CRF=1, un correo por llamada), el **caso típico** y el **mejor caso** (CRF=1.000, mil correos por llamada).\n\nLos puntos de inflexión marcan el momento en que una restricción — rate limit o cuota — pasa a ser el cuello de botella dominante.`,
    demoChartUrl: '/demo-capacity-curve.html',
  },
];

export const PROMPT_PRESETS: PromptPreset[] = [
  {
    id: 'capacity-at',
    label: 'How many calls in 5 days?',
    description: 'Calculate accumulated API capacity available after 5 days with a 100 req/day rate.',
    question:
      'If my API plan allows 100 requests per day, how many total API calls can I make in 5 days?',
    context: [],
  },
  {
    id: 'min-time',
    label: 'Time to reach 500 calls',
    description: 'Find the minimum time needed to accumulate 500 API calls under a rate limit.',
    question:
      'With a rate limit of 100 requests per day, how long does it take to reach 500 API calls?',
    context: [],
  },
  {
    id: 'quota-exhaustion',
    label: 'How fast can I exhaust my monthly quota?',
    description: 'Compute the minimum time to burn through a 1000 req/month quota at max speed.',
    question:
      'If I have a quota of 1000 requests per month and a rate limit of 10 requests per minute, how fast can I exhaust the monthly quota going at full speed? And how long will I be blocked afterwards?',
    context: [],
  },
];
