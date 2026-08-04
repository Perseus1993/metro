# 12. Seriani & Fernandez (2015) - Metro boarding and alighting management

## Evidence status

- Status: `metadata_verified`
- Evidence level: official abstract and publisher highlights only; no legally downloadable full text was found.
- Local PDF: none, intentionally. The Elsevier page offers organizational access/purchase, and the Universidad de los Andes record exposes metadata and an abstract but no file.
- Excluded source: a ResearchGate result was not archived because its version and redistribution basis were not sufficiently clear.
- Search audit: OpenAlex currently classifies the article as closed access and reports no repository location with full text. This supports, but does not by itself prove, the negative search result.

## Verified citation

Sebastian Seriani and Rodrigo Fernandez. "Pedestrian traffic management of boarding and alighting in metro stations." *Transportation Research Part C: Emerging Technologies* 53 (2015): 76-92. DOI: [10.1016/j.trc.2015.02.003](https://doi.org/10.1016/j.trc.2015.02.003).

Metadata was independently matched on the Elsevier publisher page, Crossref, and the authors' Universidad de los Andes research portal. The publication date shown by the institutional record is 1 April 2015.

## Research question and method - abstract-level evidence

The official abstract says the study asks how pedestrian traffic-management measures affect boarding and alighting time at metro stations. It combines LEGION Studio microsimulation with laboratory experiments in a mock-up comprising a metro-car vestibule and the adjacent platform. The tested factors include vertical-handrail location, a keep-out zone in front of the doors, and differentiated doors for boarding and alighting. Reported outcome families are Passenger Service Time (PST), Pedestrian Level of Service, passenger densities in the vehicle and on the platform, and passenger dissatisfaction.

## What the available source directly supports

- Boarding/alighting performance is treated as an interface process affected by both vehicle layout and platform-side traffic management, not merely as agents crossing a line.
- Simulation and controlled physical experiments are used together to compare management scenarios.
- The official publisher highlights report that vertical-handrail placement significantly affects PST and that differentiated boarding/alighting doors gave the best laboratory results among the tested arrangements.
- The abstract supports a multi-metric evaluation: PST, local density, level of service, and dissatisfaction are all part of the study's output space.

The last two points remain `abstract_or_highlight_evidence`; effect sizes, uncertainty, exact conditions, and statistical procedures cannot be checked without the article body.

## Project interpretation - not a direct claim by the paper

- The train-platform boundary should be represented as an explicit service interface whose behavior changes with door state, alighting demand, boarding demand, local occupancy, and management rules.
- A sequence such as train arrival -> doors open -> alighting/boarding interaction -> transfer complete -> doors close is a reasonable software interpretation, but the available abstract does **not** prescribe a particular state-machine implementation.
- Door-side keep-out regions and separated flows should be scenario controls, not unconditional defaults.

## Limits and prohibited overclaims

- Full methods, participant/sample details, calibration settings, effect magnitudes, and robustness checks have not been verified.
- The available evidence does not justify importing a numerical PST formula, threshold, force parameter, or universal best layout.
- The study does not establish a complete station passenger model, route-choice model, train timetable model, or production state machine.
- Results from the tested mock-up should not be generalized to this project's train geometry and passenger mix without local validation.

## Testable requirements derived for this project

1. The boarding/alighting subsystem must expose PST or an equivalent door-service-time measure per stop and per door.
2. Validation output must include time-resolved boarding and alighting counts plus platform-side and vehicle-side local density; total dwell time alone is insufficient.
3. Scenario tests should independently toggle at least door-flow separation, door-front keep-out geometry, and vestibule obstacles/handrails.
4. When both boarding and alighting demand are present, tests must verify conservation of passenger counts across platform, doorway, and vehicle states.
5. Any claim that a management layout improves operations must be checked over repeated stochastic runs and, ideally, controlled empirical observations rather than a single animation.

## Theoretical tier recommendation

- Station-interface evidence: **B+ / domain-specific experimental anchor**.
- Overall theoretical foundation: **not a holy grail**. It is narrower than the system's strategic/tactical foundations and currently downgraded by the lack of verified full text.

## Legal access points

- Publisher landing page: https://www.sciencedirect.com/science/article/abs/pii/S0968090X15000431
- Author-institution metadata record: https://investigadores.uandes.cl/en/publications/pedestrian-traffic-management-of-boarding-and-alighting-in-metro--3/
