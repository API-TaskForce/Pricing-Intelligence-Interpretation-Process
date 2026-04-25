import type { PromptPreset } from './types';

export const SENDGRID_PRESETS: PromptPreset[] = [
  {
    id: 'sg-min-time-30k',
    label: '⏱ 30.000 correos',
    description: '¿Cuánto tardo en enviar 30.000 correos en todos los planes?',
    question: '¿Cuánto tardo en enviar 30.000 correos?',
    context: [],
  },
  {
    id: 'sg-min-time-40k-pro',
    label: '⏱ 40.000 correos — Pro',
    description: 'Tiempo mínimo para 40.000 correos centrándome en el plan Pro.',
    question: '¿Si me centro en el plan Pro, cuánto tardo en enviar 40.000 correos?',
    context: [],
  },
  {
    id: 'sg-min-time-1300',
    label: '⏱ 1.300 correos',
    description: '¿Cuánto tiempo necesito para enviar 1.300 correos en todos los planes?',
    question: '¿Cuánto tiempo necesito para enviar 1.300 correos?',
    context: [],
  },
  {
    id: 'sg-min-time-1300-pro',
    label: '⏱ 1.300 correos — Pro',
    description: 'Tiempo mínimo para 1.300 correos en el plan Pro específicamente.',
    question: '¿Si me centro en el plan Pro, cuánto tiempo necesito para enviar 1.300 correos?',
    context: [],
  },
  {
    id: 'sg-best-plan-1200',
    label: '💡 1.200 correos/día — ¿qué plan?',
    description: 'Mejor plan para enviar 1.200 correos diarios, considerando tiempo y precio.',
    question: '¿Si necesito enviar 1.200 correos en un día, cuál es el plan que más me conviene? Teniendo en cuenta el tiempo de envío y su precio.',
    context: [],
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
