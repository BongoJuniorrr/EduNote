export type NotebookRecordType =
  | "solve"
  | "question"
  | "research"
  | "co_writer"
  | "chat"
  | "note"
  | "canvas"
  | "slide_pro";

export const NOTEBOOK_RECORD_LABEL: Record<NotebookRecordType, string> = {
  solve: "Solver",
  question: "Question",
  research: "Research",
  co_writer: "Co-Writer",
  chat: "Chat",
  note: "Note",
  canvas: "Canvas",
  slide_pro: "Slide Pro",
};

