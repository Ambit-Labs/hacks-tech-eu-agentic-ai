/**
 * The single place the chat's language model is chosen.
 *
 * The route handler imports from here, so swapping providers is one edit in
 * this file. Keep provider names and
 * provider-specific options inside this module.
 */

import { createGoogleGenerativeAI } from "@ai-sdk/google";
import type { LanguageModel } from "ai";

const MODEL_ID = "gemini-3.8-flash";

const API_KEY_ENV = "GOOGLE_AI_STUDIO_KEY";

/** Name of the env var the route reports when the model cannot be built. */
export const CHAT_MODEL_API_KEY_ENV = API_KEY_ENV;

/** True when the server has the credentials the model needs. */
export function isChatModelConfigured(): boolean {
  return Boolean(process.env[API_KEY_ENV]);
}

/** Builds the language model. Call only after `isChatModelConfigured()`. */
export function getChatModel(): LanguageModel {
  const apiKey = process.env[API_KEY_ENV];

  if (!apiKey) {
    throw new Error(`${API_KEY_ENV} is not set.`);
  }

  return createGoogleGenerativeAI({ apiKey })(MODEL_ID);
}

/**
 * Provider-specific call options. The low thinking level keeps replies fast.
 * Thought summaries are requested, but this model returned none in testing at
 * any thinking level, so the reasoning card stays unused until they show up.
 */
export const CHAT_MODEL_PROVIDER_OPTIONS = {
  google: {
    thinkingConfig: {
      includeThoughts: true,
      thinkingLevel: "low",
    },
  },
};
