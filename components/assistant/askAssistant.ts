"use client";

import { assistantService } from "@/services";
import { useUi } from "@/store/ui";
import type { AssistantMessage } from "@/types/assistant";

let seq = 0;
const uid = () => `m${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** Open the assistant and send a question (from the drawer, palette or a suggestion chip). */
export async function askAssistant(text: string) {
  const query = text.trim();
  if (!query || useUi.getState().assistantPending) return;
  const user: AssistantMessage = { id: uid(), role: "user", text: query, at: Date.now() };
  useUi.setState((s) => ({ assistantOpen: true, assistantPending: true, assistantMessages: [...s.assistantMessages, user] }));
  try {
    const response = await assistantService.ask(query, useUi.getState().assistantMessages);
    const reply: AssistantMessage = { id: uid(), role: "assistant", text: response.text, at: Date.now(), response };
    useUi.setState((s) => ({ assistantMessages: [...s.assistantMessages, reply] }));
  } catch {
    const reply: AssistantMessage = { id: uid(), role: "assistant", text: "Something went wrong while querying operations data. Please try again.", at: Date.now() };
    useUi.setState((s) => ({ assistantMessages: [...s.assistantMessages, reply] }));
  } finally {
    useUi.setState({ assistantPending: false });
  }
}
