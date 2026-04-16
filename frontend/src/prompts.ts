import type { PromptPreset } from './types';

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
