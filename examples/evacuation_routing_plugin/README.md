# Example evacuation-routing plugin

This directory is a copyable, standalone SDK template. `plugin.py` imports only the Python standard library and communicates with the metro-station host through one-line JSON on stdin/stdout.

Validate it from the repository environment:

```powershell
metro-station validate-routing-plugin examples/evacuation_routing_plugin/manifest.json
```

The command must report 10/10 cases before the plugin is used in an experiment. See `docs/sdk/EVACUATION_ROUTING_PLUGIN.md` for the protocol, validation rules, failure model, and safety boundary.
