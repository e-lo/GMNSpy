# netstead-hello

A minimal netstead Workbench plugin. Install it next to netstead, and `netstead app` loads it:

```bash
uv pip install -e examples/workbench-plugin-hello
```

The plugin adds the following:

- the `hello.greet` Action
- the `[plugins.hello] prefix` setting
- state under `plugins.hello`
- `GET /api/plugins/hello/count`
- a front-end module at `/plugins/hello/main.js` (the browser loader that runs it arrives with the Workbench's plugin front end; until then the file is only served)

To turn it off without uninstalling it, set `[app] disabled_plugins = ["hello"]`.

Plugins are full-trust Python running inside the Workbench process. See the
[Write a Workbench plugin](../../packages/netstead/docs/cookbook/workbench-plugins.md) cookbook page.
