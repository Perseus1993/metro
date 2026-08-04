# 15. Curtis, Best & Manocha (2016) - Menge modular crowd framework

## Evidence status

- Status: `full_text_verified`
- Full text: `../papers/15_2016_Curtis_Menge_modular_framework.pdf`
- Version: final journal PDF from *Collective Dynamics*, CC BY 4.0.
- PDF verification: valid, unencrypted PDF 1.5; 40 pages; the first page matches title, authors, journal, article number, year and DOI. Poppler reported a recoverable legacy cross-reference warning, but both extraction and rendering succeeded.
- SHA-256: `CF026A4EFCD62D3D2BD1C484EFB9DB7564E4DB6834E662EC47A80333B656F515`

## Verified citation

Sean Curtis, Andrew Best, and Dinesh Manocha. "Menge: A Modular Framework for Simulating Crowd Movement." *Collective Dynamics* 1 (2016), article A1, 1-40. DOI: [10.17815/CD.2016.1](https://doi.org/10.17815/CD.2016.1).

## Research question

How can a crowd simulator be decomposed so researchers can replace, combine and compare solutions to individual subproblems without repeatedly rebuilding the entire system?

## What the paper directly supports

Menge decomposes crowd movement into:

1. **Goal selection** - what the agent seeks to achieve.
2. **Plan computation** - a static/global plan expressed as preferred velocity.
3. **Plan adaptation** - local/dynamic conversion of preferred velocity into feasible velocity; Social Force and velocity-obstacle models fit here.
4. **Environmental queries** - visibility, proximity, elevation and related shared services.
5. **Motion synthesis** - visual body motion, explicitly outside the released framework's main scope.

The architecture then realizes those subproblems through replaceable elements:

- a Behavioral Finite State Machine (BFSM) for agent activities and transitions;
- goal and goal-selector elements, including finite-capacity goals;
- velocity components and composable velocity modifiers;
- pedestrian-model elements that map preferred to feasible velocity;
- spatial-query, elevation, task and event elements;
- agent/profile/state generators and an extensible XML scenario format.

The paper demonstrates module substitution while holding the rest of a scenario fixed: local models are compared in a cross-flow scene and global planners in an obstacle course. It also demonstrates multi-activity BFSM scenarios, multi-floor representations, event-driven behavior, density-dependent modifiers and 16k/32k/64k-agent scaling experiments.

## Project interpretation - not a direct claim by the paper

- The production simulator should separate at least `goal/activity`, `tactical route/plan`, `preferred velocity`, `local feasible motion`, `agent state transition`, `environment query`, `external event`, and `measurement/output` responsibilities.
- Train arrival, door opening, facility closure and crowd-control instructions are natural external events; passenger progression such as entering, queuing, boarding and riding is natural agent state.
- A clean benchmark should swap one planner or local-motion implementation while keeping demand, geometry, seed and metrics fixed.

## What the paper does **not** prove

- Modularity does not establish behavioral realism, empirical calibration, safety validity or correctness of any included pedestrian model.
- Menge's examples are architecture demonstrations, not validation of this metro station.
- Its elevation mapping and disconnected-floor examples show engineering representations of complex topology; they do not establish a universal physical model for stairs, escalators or elevators.

## Explicit limitations in the paper

- High-level behavior is limited to BFSM; behavior trees are not supported by the exposed traversal interface.
- Planning/objective and personality/mood are tightly coupled in one FSM state, which can force redundant states.
- Motion synthesis is excluded.
- The framework assumes agent-based movement and is not naturally aligned with motion-patch approaches.
- The 2016 implementation uses primitive synchronization that limits parallel scaling.
- Population is fixed during a run; agents cannot yet be introduced or removed dynamically.

These are version-specific observations from the paper, not claims about the current state of a later Menge codebase.

## Testable architecture requirements derived for this project

1. A tactical planner must output a documented preferred direction/velocity contract; the local-motion model must consume it and output feasible motion without owning activity selection.
2. Activity/state transitions and exogenous events must be separately testable. Closing a facility should alter availability/cost and trigger only the intended state or route responses.
3. Each algorithmic family must be selectable by configuration through a validated interface; unknown parameters and incompatible combinations must fail clearly.
4. An A/B harness must run the same scenario and random-seed set with exactly one module changed, preserving demand, geometry and metrics.
5. Metrics and visualization must observe state without becoming authoritative state owners.
6. Dynamic passenger creation/removal, train-door exchange and multi-floor transfer are project requirements that must not inherit Menge 2016's fixed-population limitation.
7. Architecture tests must be paired with independent behavioral tests; passing dependency/interface tests is not model validation.

## Theoretical tier recommendation

- Software decomposition and experimental comparability: **A / engineering architecture anchor**.
- Behavioral or empirical legitimacy: **C / not evidence of correctness**.
- It should guide the code audit, but must never be presented as the scientific basis for parameter values or passenger behavior.

## Source

- Journal landing page: https://collective-dynamics.eu/index.php/cod/article/view/A1
- Archived PDF source: https://collective-dynamics.eu/index.php/cod/article/download/A1/3/26

