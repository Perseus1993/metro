from __future__ import annotations

from dataclasses import replace
from math import hypot

import pytest
from shapely.geometry import Point as ShapelyPoint, Polygon

from metro_station.adapters.simulation.compilation.facility_portals import (
    _topology_fingerprint,
    compile_facility_portal_bindings,
    compile_reversed_escalator_portal_binding,
    validate_facility_portals,
    validate_portal_binding_configuration,
)
from metro_station.adapters.simulation.compilation.facility_portal_validation import (
    _point_issues,
)
from metro_station.adapters.simulation.compilation.geometry_reachability import (
    GeometryCompilePolicy,
)
from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.design.geometry import element_shape
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.design.templates import create_design, topology_templates
from metro_station.adapters.simulation.design.vertical_landing import (
    vertical_landing_outward_direction,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station.adapters.simulation.station.layout_facilities import (
    _facility_specs_from_station_graph,
)
from metro_station.adapters.simulation.station.layout_gate_queues import (
    _gate_split_axis,
    _gate_to_local,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.facilities.process import QueueLayout
from metro_station.adapters.simulation.runtime.passenger_goal_region_router import (
    PassengerGoalRegionRouter,
)
from metro_station_testkit.layout_corpus import generate_geometry_scenario_matrix
from metro_station_testkit.layout_scenario_generator import generate_layout


def test_reversed_escalator_synthetic_lane_can_coexist_with_authored_opposite_queue() -> None:
    document = create_design("three_level_transfer")
    scenario = _scenario(document)
    graph = StationGraph.from_design(document)
    policy = GeometryCompilePolicy.from_scenario(scenario)
    facilities = tuple(_facility_specs_from_station_graph(graph, scenario))
    bindings = compile_facility_portal_bindings(
        document,
        facilities,
        policy=policy,
        graph=graph,
    )
    facility = next(
        item
        for item in facilities
        if item.kind == "escalator" and item.direction == "up"
    )
    binding = next(item for item in bindings if item.facility_id == facility.facility_id)

    reversed_spec, reversed_binding = compile_reversed_escalator_portal_binding(
        document,
        facility,
        binding,
        policy=policy,
    )
    issues = validate_facility_portals(
        document,
        (reversed_spec,),
        (reversed_binding,),
        policy=policy,
    )

    assert not [issue for issue in issues if issue.severity == "error"]


def test_all_formal_templates_have_complete_strict_portal_bindings() -> None:
    templates = topology_templates()
    assert {template.id for template in templates} == {
        "single_level_terminal",
        "two_level_island_platform",
        "three_level_transfer",
        "visual_demo_station",
    }
    for template in templates:
        document = create_design(template.id)
        layout = DesignCompiler.compile(document, _scenario(document))

        assert layout.facilities
        assert len(layout.facility_portal_bindings) == len(layout.facilities)
        assert not [
            binding for binding in layout.facility_portal_bindings if binding.fallback_used
        ]
        assert all(binding.queue_slots for binding in layout.facility_portal_bindings)
        model = MetroStationModel(_scenario(document))
        for facility in model.facilities:
            binding = model.facility_portal_binding(facility.facility_id)
            assert tuple(
                facility.queue.layout.slot(index)
                for index in binding.approach_slot_indices
            ) == binding.approach_slots


def test_vertical_near_entry_prefix_is_bridge_without_losing_waiting_capacity() -> None:
    document = create_design("visual_demo_station")
    layout = DesignCompiler.compile(document, _scenario(document))
    binding = next(
        item
        for item in layout.facility_portal_bindings
        if item.facility_id
        == "vertical:down_escalator_b:down:b1_concourse:b2_platform"
    )
    bridges = tuple(
        item for item in binding.queue_slot_bindings if item.role == "bridge"
    )

    assert bridges
    assert all(item.service_rank is None for item in bridges)
    assert all(item.runtime_slot_index is None for item in bridges)
    assert len(binding.approach_slots) == binding.source_queue_capacity
    assert min(
        hypot(
            point[0] - binding.entry_point[0],
            point[1] - binding.entry_point[1],
        )
        for point in binding.approach_slots
    ) >= 1.0 - 1e-7
    path = (binding.entry_point, *(item.position for item in bridges), *binding.approach_slots)
    assert all(
        hypot(right[0] - left[0], right[1] - left[1])
        <= binding.queue_spacing_m * 1.75 + 1e-7
        for left, right in zip(path, path[1:])
    )


def test_binding_ids_must_match_facilities_one_to_one() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    duplicated = (
        layout.facility_portal_bindings[0],
        layout.facility_portal_bindings[0],
        *layout.facility_portal_bindings[2:],
    )
    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            duplicated,
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.missing" in codes


def test_facility_and_binding_ids_must_each_be_unique() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    facilities = list(layout.facilities)
    bindings = list(layout.facility_portal_bindings)
    facilities[1] = replace(facilities[1], facility_id=facilities[0].facility_id)
    bindings[1] = replace(
        bindings[1],
        facility_id=bindings[0].facility_id,
        facade_key=f"{bindings[1].facade_key}:duplicate-id-regression",
    )

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.duplicate_facility_id" in codes
    assert "portals.duplicate_binding_id" in codes


def test_binding_ids_cannot_be_swapped_between_facades() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    bindings = list(layout.facility_portal_bindings)
    first_id = bindings[0].facility_id
    second_id = bindings[1].facility_id
    bindings[0] = replace(bindings[0], facility_id=second_id)
    bindings[1] = replace(bindings[1], facility_id=first_id)

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.binding_identity_mismatch" in codes


def test_approach_projection_and_runtime_indices_are_locked_to_compiled_slots() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    index = next(
        index
        for index, binding in enumerate(layout.facility_portal_bindings)
        if len(binding.approach_slots) >= 2
    )
    binding = layout.facility_portal_bindings[index]
    broken = replace(
        binding,
        approach_slots=(binding.approach_slots[0], binding.approach_slots[0]),
        approach_source_slot_indices=(
            binding.approach_source_slot_indices[0],
            binding.approach_source_slot_indices[1],
        ),
        approach_slot_indices=(
            binding.approach_slot_indices[0],
            binding.approach_slot_indices[0],
        ),
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[index] = broken

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "queues.slot_projection_mismatch" in codes


def test_runtime_slot_index_cannot_be_relabelled_away_from_runtime_position() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    binding_index = next(
        index
        for index, binding in enumerate(layout.facility_portal_bindings)
        if len(binding.approach_slot_indices) >= 2
    )
    binding = layout.facility_portal_bindings[binding_index]
    first, second = binding.approach_slot_indices[:2]
    changed_slots = tuple(
        replace(
            slot,
            runtime_slot_index=(
                second
                if slot.runtime_slot_index == first
                else first
                if slot.runtime_slot_index == second
                else slot.runtime_slot_index
            ),
        )
        for slot in binding.queue_slot_bindings
    )
    changed = replace(
        binding,
        queue_slot_bindings=changed_slots,
        approach_slot_indices=(
            second,
            first,
            *binding.approach_slot_indices[2:],
        ),
        topology_fingerprint=_topology_fingerprint(changed_slots),
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[binding_index] = changed

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.binding_identity_mismatch" in codes


def test_gate_entry_and_exit_must_be_on_opposite_facades() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    gate_index = next(
        index
        for index, binding in enumerate(layout.facility_portal_bindings)
        if binding.kind == "gate"
    )
    gate = layout.facility_portal_bindings[gate_index]
    same_side = replace(
        gate,
        raw_exit_point=gate.raw_entry_point,
        exit_point=gate.entry_point,
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[gate_index] = same_side
    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.facade_mismatch" in codes


def test_queue_slots_cannot_be_reused_across_facades() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    by_queue: dict[str, list[int]] = {}
    for index, binding in enumerate(layout.facility_portal_bindings):
        if binding.queue_id is not None:
            by_queue.setdefault(binding.queue_id, []).append(index)
    first, second = next(indices[:2] for indices in by_queue.values() if len(indices) >= 2)
    bindings = list(layout.facility_portal_bindings)
    bindings[second] = replace(
        bindings[second],
        queue_slots=bindings[first].queue_slots,
        approach_slots=bindings[first].approach_slots,
        approach_point=bindings[first].approach_point,
    )
    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "queues.slot_overlap" in codes


def test_physical_slots_cannot_overlap_across_different_queue_ids() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    first, second = next(
        (left, right)
        for left, left_binding in enumerate(layout.facility_portal_bindings)
        for right, right_binding in enumerate(layout.facility_portal_bindings)
        if left < right
        and left_binding.entry_level_id == right_binding.entry_level_id
        and left_binding.queue_id != right_binding.queue_id
        and left_binding.approach_slots
        and right_binding.approach_slots
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[second] = replace(
        bindings[second],
        approach_slots=bindings[first].approach_slots,
    )
    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "queues.slot_overlap" in codes


def test_runtime_queue_spec_mutation_cannot_override_compiled_decision_points() -> None:
    document = create_design("single_level_terminal")
    model = MetroStationModel(_scenario(document))
    facility = model.gates[0]
    binding = model.facility_portal_binding(facility.facility_id)
    facility.spec = replace(
        facility.spec,
        queue_layout=QueueLayout(
            anchor=(10.0, 10.0),
            per_row=1,
            col_step=(0.0, 0.0),
            row_step=(0.0, 0.0),
            slots=((10.0, 10.0),),
        ),
    )

    points = PassengerGoalRegionRouter()._facility_decision_points(
        model,
        None,
        facility,
    )

    assert points == binding.approach_slots
    assert (10.0, 10.0) not in points
    assert facility._mechanical_service_entry_position() == binding.entry_point
    assert facility._mechanical_service_release_position() == binding.exit_point


def test_runtime_spec_mutation_cannot_change_compiled_release_axes() -> None:
    document = create_design("three_level_transfer")
    model = MetroStationModel(_scenario(document))
    facility = next(item for item in model.vertical_transports if item.spec.kind == "elevator")
    expected = facility._release_axes()
    facility.spec = replace(
        facility.spec,
        queue_layout=replace(facility.spec.queue_layout, anchor=(999.0, -777.0)),
    )

    assert facility._release_axes() == expected
    assert expected == (
        facility.portal_binding.release_forward,
        facility.portal_binding.release_lateral,
    )


def test_stacked_generated_elevator_release_uses_authored_door_normal() -> None:
    recipe = next(
        item
        for item in generate_geometry_scenario_matrix().recipes
        if item.recipe_id
        == "geometry-two_level_island-rect-full-bidirectional-seed-7"
    )
    document = generate_layout(recipe)
    compiled = validate_compiled_station_design(document, _scenario(document))
    binding = next(
        item
        for item in compiled.facility_portal_bindings
        if item.facility_id
        == "vertical:elevator_a:up:b2_platform:b1_concourse"
    )
    element = document.element_by_id()[binding.source_element_id]
    outward = vertical_landing_outward_direction(element)

    assert binding.entry_point == binding.exit_point
    assert (
        binding.release_forward[0] * outward[0]
        + binding.release_forward[1] * outward[1]
    ) >= 0.999
    release = next(
        item
        for item in compiled.spatial_capacity_certificates
        if item.resource_kind == "release_apron"
        and item.owner_id == binding.facility_id
    )
    assert release.certified_body_capacity == release.required_body_capacity == 12


def test_runtime_queue_capacity_is_the_compiled_occupiable_capacity() -> None:
    document = create_design("visual_demo_station")
    model = MetroStationModel(_scenario(document))

    for facility in model.facilities:
        binding = model.facility_portal_binding(facility.facility_id)
        assert binding.declared_queue_capacity == len(binding.approach_slots)
        assert binding.source_queue_capacity >= binding.declared_queue_capacity
        assert facility.queue.max_length == binding.declared_queue_capacity


def test_configuration_uses_formal_two_body_clearance_policy() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    first, second = layout.facility_portal_bindings[:2]
    bindings = (
        replace(
            first,
            entry_level_id="clearance_fixture",
            approach_slots=((0.0, 0.0),),
            activation_group_id=None,
            activation_variant_id=None,
        ),
        replace(
            second,
            entry_level_id="clearance_fixture",
            approach_slots=((0.38, 0.0),),
            activation_group_id=None,
            activation_variant_id=None,
        ),
    )

    issues = validate_portal_binding_configuration(
        bindings,
        policy=GeometryCompilePolicy(
            agent_radius_m=0.18,
            clearance_multiplier=2.2,
        ),
    )

    assert {item.code for item in issues} == {"queues.slot_clearance_conflict"}


def test_portal_clearance_requires_two_agent_radii() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    binding = replace(
        layout.facility_portal_bindings[0],
        entry_level_id="clearance_fixture",
        exit_level_id="clearance_fixture",
        raw_entry_point=(0.27, 5.0),
        entry_point=(0.27, 5.0),
        approach_point=(0.27, 5.0),
        raw_exit_point=(0.27, 6.0),
        exit_point=(0.27, 6.0),
        queue_slots=((1.0, 5.0),),
    )
    domain = Polygon(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    policy = GeometryCompilePolicy(agent_radius_m=0.18, clearance_multiplier=2.2)

    issues = _point_issues(
        binding,
        {"clearance_fixture": domain},
        {"clearance_fixture": domain.buffer(-policy.agent_radius_m)},
        policy,
        "facilities.clearance_fixture",
    )

    assert "portals.clearance_too_small" in {item.code for item in issues}


def test_rotated_bidirectional_gate_uses_transformed_facades_and_directional_queues() -> None:
    document = create_design("single_level_terminal")
    gate = next(element for element in document.elements if element.kind == "gate")
    rotated = replace(gate, geometry=replace(gate.geometry, rotation_deg=45.0))
    changed = replace(
        document,
        elements=tuple(rotated if element.id == gate.id else element for element in document.elements),
        queues=tuple(queue for queue in document.queues if queue.owner_element_id != gate.id),
    )
    generated = generate_station(changed)
    layout = DesignCompiler.compile(generated, _scenario(generated))
    bindings = tuple(
        binding
        for binding in layout.facility_portal_bindings
        if binding.source_element_id == gate.id
    )
    transformed_boundary = element_shape(rotated.geometry).boundary

    assert bindings
    assert {binding.direction for binding in bindings} == {"in", "out"}
    assert not any(binding.fallback_used for binding in bindings)
    assert all(
        transformed_boundary.distance(ShapelyPoint(binding.entry_point)) <= 0.02
        and transformed_boundary.distance(ShapelyPoint(binding.exit_point)) <= 0.02
        for binding in bindings
    )


def test_rotated_gate_queue_lanes_remain_parallel_in_gate_local_frame() -> None:
    base = create_design("single_level_terminal")
    gate = next(element for element in base.elements if element.kind == "gate")
    checked_lanes = 0

    for rotation_deg in (0.0, 31.0, 45.0, 90.0, 173.0, 271.0):
        rotated = replace(
            gate,
            geometry=replace(gate.geometry, rotation_deg=rotation_deg),
        )
        changed = replace(
            base,
            elements=tuple(
                rotated if element.id == gate.id else element
                for element in base.elements
            ),
            queues=tuple(
                queue
                for queue in base.queues
                if queue.owner_element_id != gate.id
            ),
        )
        generated = generate_station(changed)
        layout = DesignCompiler.compile(generated, _scenario(generated))
        bindings = tuple(
            binding
            for binding in layout.facility_portal_bindings
            if binding.source_element_id == gate.id
        )
        split_axis = _gate_split_axis(rotated)
        lateral_axis = 0 if split_axis == "x" else 1
        for binding in bindings:
            local = tuple(
                _gate_to_local(rotated, point)
                for point in binding.approach_slots[:4]
            )
            assert len(local) == 4
            assert max(point[lateral_axis] for point in local) - min(
                point[lateral_axis] for point in local
            ) <= 1e-3
            assert all(
                ShapelyPoint(left).distance(ShapelyPoint(right)) == pytest.approx(
                    0.8,
                    abs=1e-3,
                )
                for left, right in zip(local, local[1:])
            )
            checked_lanes += 1

    assert checked_lanes == 72


def test_missing_directional_queue_is_a_portal_error_not_a_runtime_fallback() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    graph = StationGraph.from_design(document)
    facilities = tuple(_facility_specs_from_station_graph(graph, scenario))
    queue_id = next(queue.id for queue in document.queues if queue.service_direction == "in")
    changed = replace(
        document,
        queues=tuple(queue for queue in document.queues if queue.id != queue_id),
    )
    policy = GeometryCompilePolicy.from_scenario(scenario)
    bindings = compile_facility_portal_bindings(changed, facilities, policy=policy)
    codes = {
        item.code
        for item in validate_facility_portals(
            changed,
            facilities,
            bindings,
            policy=policy,
        )
    }

    assert "portals.missing" in codes


def test_outside_queue_slot_is_rejected_by_body_safe_domain() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    first = layout.facility_portal_bindings[0]
    broken = replace(first, queue_slots=((*first.queue_slots[:-1], (-100.0, -100.0))))
    bindings = (broken, *layout.facility_portal_bindings[1:])
    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            bindings,
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "queues.slot_outside_safe_core" in codes
    assert "queues.slot_projection_mismatch" in codes


def test_portal_levels_must_exist_in_compiled_domain_set() -> None:
    document = create_design("visual_demo_station")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    binding = layout.facility_portal_bindings[0]
    broken = replace(binding, entry_level_id="missing_level")
    bindings = (broken, *layout.facility_portal_bindings[1:])

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            bindings,
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.level_mismatch" in codes


def test_vertical_portals_must_resolve_to_opposite_levels() -> None:
    document = create_design("visual_demo_station")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    binding_index = next(
        index
        for index, binding in enumerate(layout.facility_portal_bindings)
        if binding.kind in {"stairs", "escalator", "elevator"}
    )
    binding = layout.facility_portal_bindings[binding_index]
    broken = replace(
        binding,
        raw_exit_point=binding.raw_entry_point,
        exit_point=binding.entry_point,
        exit_level_id=binding.entry_level_id,
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[binding_index] = broken

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "portals.same_side" in codes


def test_duplicate_queue_slot_is_detached_from_entry() -> None:
    document = create_design("single_level_terminal")
    scenario = _scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    binding_index = next(
        index
        for index, binding in enumerate(layout.facility_portal_bindings)
        if len(binding.queue_slots) >= 2
    )
    binding = layout.facility_portal_bindings[binding_index]
    broken = replace(
        binding,
        queue_slots=(binding.queue_slots[0], binding.queue_slots[0], *binding.queue_slots[2:]),
    )
    bindings = list(layout.facility_portal_bindings)
    bindings[binding_index] = broken

    codes = {
        item.code
        for item in validate_facility_portals(
            document,
            layout.facilities,
            tuple(bindings),
            policy=GeometryCompilePolicy.from_scenario(scenario),
        )
    }

    assert "queues.slot_detached_from_entry" in codes


def test_adjacent_slots_in_one_queue_require_two_body_clearance() -> None:
    document = create_design("single_level_terminal")
    queue = next(
        item
        for item in document.queues
        if item.owner_element_id == "platform_edge_a"
    )
    changed = replace(
        document,
        queues=tuple(
            replace(queue, spacing_m=0.4, capacity=2)
            if item.id == queue.id
            else item
            for item in document.queues
        ),
    )
    scenario = replace(
        _scenario(changed),
        jupedsim_agent_radius_units=0.22,
    )
    compiled = validate_compiled_station_design(changed, scenario)

    assert "queues.slot_clearance_conflict" in {
        item.code for item in compiled.issues
    }


def _scenario(document) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"portal_contract_{document.id}",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="facility_portal_binding_test",
        sample_hours=1,
        station_design=document,
        audit_enabled=False,
        audit_print_events=False,
    )
