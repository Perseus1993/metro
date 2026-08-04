# B1 station element visual trial catalog

Scope: isolated Unity visual sample only. `Visual only` means the object does
not change routing, collision, queueing, capacity, service time or passenger
decisions. Any item that would affect those outcomes must later be represented
explicitly in the upstream station model.

| Group | Trial coverage | Source / status | Upstream implication |
|---|---|---|---|
| Fire and smoke | HDRP flame, smoke and flicker light | Vefects VFX Free Fire | Fire location, growth and smoke tenability are not simulated |
| Temporary cordon | Red/yellow water barriers | OpenGameArt, CC0 | Needs obstacle geometry and activation time upstream |
| Security checkpoint | Existing provisional X-ray visual, console and two guards | Existing station set; Kenney CC0 scanner candidates rejected after in-scene review | Scanner lanes, tray service and queues need upstream facilities |
| Fire equipment | Extinguisher cabinet, extinguisher, manual alarm | Existing station asset plus Poly Haven CC0 | Availability, reach and activation are not simulated |
| Electrical / MEP | Electrical cabinet, sparks, CCTV, ceiling lights | Poly Haven CC0 plus existing assets | Clearance envelopes and hazards need upstream geometry/events |
| Operations | Wall clock, displays, help point, ticket machines, service center | Poly Haven/Kenney plus station assets | Help/ticket/service interactions need explicit service nodes |
| Wayfinding | Exit signs, ticket/security labels, gate arrows | Project-authored B1 visual protocol | Sign visibility and passenger compliance are not model inputs |
| Accessibility | Wide gate, tactile route, wheelchair trial | B1 layout plus Poly Haven CC0 | Wheelchair kinematics and accessible route choice need upstream agents |
| Platform | Safety/tactile line, queue markers, platform doors/train layer | Existing platform presentation | Door states, capacity and queues remain upstream responsibilities |
| Passengers | Adult, business, sports, party and four child bases | Microsoft Rocketbox, MIT | No explicit elderly, stroller, cane or luggage behavior yet |
| Staff / response | Security, fire, medical, police and maintenance trial | Microsoft Rocketbox, MIT | Dispatch, authority and intervention logic are not modeled here |
| Daily furniture | Benches, bins, displays, vending, plants and doorway | Kenney CC0 plus local prototype assets | Only route-blocking furniture needs upstream footprints |
| Cleaning | Push broom and cleaner bottle | Poly Haven CC0; CoffeeCart candidate rejected after in-scene review | A parked/moving cleaning trolley needs an upstream footprint and state |
| Robot | Not accepted yet | Exact free bucket-style hotel robot still missing | Robot path, footprint and interactions require upstream agent modeling |

## Known gaps after this trial

- A realistic, free hotel-style delivery robot with one enclosed bucket.
- Explicit older passengers, cane users, stroller families and luggage variants.
- A realistic X-ray tunnel with trays. The Kenney scanner/conveyor candidates
  were tested and retained in the asset folder, but rejected for the main view
  because their industrial low-poly silhouette does not meet the visual bar.
- Smoke detectors, sprinklers, audible/visual alarm units, PA speakers, AED,
  emergency lighting, stretcher and first-aid kit.
- A credible janitor trolley; the Poly Haven CoffeeCart remained visibly a
  coffee machine cart and was not kept in the scene.
- China-metro-specific sign artwork and audited bilingual wayfinding.
- Formal upstream footprints, state timelines and service/queue semantics for
  every route-affecting object.
