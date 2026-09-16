/** Fictional operations staff for the demo scenario. */
export const people = {
  analyst: { name: "Noura Al-Harbi", role: "Exception analyst", desk: "Dammam–Khobar desk", initials: "NH", email: "noura.alharbi@ops.dallal.example" },
  supervisor: {
    name: "Faisal Al-Dosari",
    role: "Shift supervisor",
    region: "Eastern Region",
    initials: "FD",
    email: "faisal.aldosari@ops.dallal.example",
  },
  branchLeadDammam: { name: "Majed Al-Qahtani", role: "Branch lead · Dammam Central" },
  agent: { name: "Dallal Agent", role: "Exception agent" },
} as const;
