// Tiny in-memory feature-flag store. The real PWA reads flags from a service
// (Statsig/LaunchDarkly); this stand-in exists so the Playwright specs can
// toggle `tasks.customColumns` before hitting /demo/tasks.

const flags = new Map<string, boolean>();

// `tasks.customColumns` starts OFF (per plan, feature stays flagged until
// step 8). The demo page and tests flip it on with a PUT /api/flags/:name.
flags.set("tasks.customColumns", true);

export function getFlag(name: string): boolean {
  return flags.get(name) ?? false;
}

export function setFlag(name: string, enabled: boolean): void {
  flags.set(name, enabled);
}
