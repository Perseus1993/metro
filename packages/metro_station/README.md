# metro-station

This is the official package for the station passenger-flow simulation. It owns the pure domain,
framework-independent application use cases, and the concrete Mesa/JuPedSim simulation adapters.
It does not import the legacy `sandbox` package, experiments, testkit, acceptance harnesses, or
presentation applications.

The designer and visualizer are optional workspace applications with their own distributions.

```powershell
metro-station simulate --minutes 1
metro-station validate-design --design-template visual_demo_station
metro-station-designer --port 8766
metro-station-visualizer --port 8765
```
