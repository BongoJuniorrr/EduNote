// Chat-specific types for home page chat

/**
 * Source references for chat messages
 */
export interface RagChatSource {
  kb_name: string;
  content: string; // backward-compatible snippet field
  provider?: string;
  chunk_id?: string | null;
  doc_id?: string | null;
  doc_name?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  section_path?: string;
  confidence?: number | null;
  snippet?: string;
  metadata?: Record<string, any>;
}

export interface ChatSource {
  rag?: RagChatSource[];
  web?: Array<{ url: string; title?: string; snippet?: string }>;
}

/**
 * Chat message with sources and streaming state
 */
export interface HomeChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource;
  isStreaming?: boolean;
}

/**
 * Chat state
 */
export interface ChatState {
  sessionId: string | null;
  messages: HomeChatMessage[];
  isLoading: boolean;
  selectedKb: string;
  enableRag: boolean;
  enableWebSearch: boolean;
  currentStage: string | null;
}

/**
 * Initial chat state
 */
export const INITIAL_CHAT_STATE: ChatState = {
  sessionId: null,
  messages: [],
  isLoading: false,
  selectedKb: "",
  enableRag: false,
  enableWebSearch: false,
  currentStage: null,
};
