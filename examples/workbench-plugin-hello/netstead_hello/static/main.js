// Loaded by the Workbench front end (Part 2): register UI against the host object `wb`.
// Until the Part 2 browser loader lands, this file is only served at /plugins/hello/main.js.
export function activate(wb) {
  wb.registerCommand?.({
    id: "hello.greet",
    title: "Say hello",
    contexts: ["palette"],
    run: () => wb.api.dispatch({ type: "hello.greet", name: "world" }),
  });
}
