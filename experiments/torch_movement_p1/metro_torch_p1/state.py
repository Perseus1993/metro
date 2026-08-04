"""Fixed-slot passenger lifecycle independent of the movement calculation."""

from __future__ import annotations

from dataclasses import replace

import torch

from .contracts import PopulationState


class SlotPopulation:
    """Owns passenger-ID/slot mapping and resets every field on slot reuse."""

    def __init__(
        self,
        *,
        batch_size: int,
        capacity: int,
        device: torch.device | str,
        dtype: torch.dtype = torch.float32,
    ) -> None:
        self._id_to_slot = [dict() for _ in range(batch_size)]
        vector = torch.zeros((batch_size, capacity, 2), device=device, dtype=dtype)
        scalar = torch.zeros((batch_size, capacity, 1), device=device, dtype=dtype)
        slots = torch.full((batch_size, capacity), -1, device=device, dtype=torch.int64)
        self._state = PopulationState(
            position=vector,
            velocity=vector.clone(),
            target=vector.clone(),
            radius=scalar,
            desired_speed=scalar.clone(),
            active_mask=torch.zeros((batch_size, capacity), device=device, dtype=torch.bool),
            level_index=slots.clone(),
            passenger_ids=slots.clone(),
        )

    @property
    def state(self) -> PopulationState:
        return self._state

    def replace_state(self, state: PopulationState) -> None:
        if state.batch_size != self._state.batch_size or state.capacity != self._state.capacity:
            raise ValueError("replacement state has incompatible slot dimensions")
        self._state = state

    def spawn(
        self,
        passenger_id: int,
        *,
        position: tuple[float, float],
        target: tuple[float, float],
        radius: float = 0.18,
        desired_speed: float = 1.2,
        level_index: int = 0,
        batch_index: int = 0,
    ) -> int:
        mapping = self._id_to_slot[batch_index]
        if passenger_id in mapping:
            raise ValueError(f"passenger {passenger_id} is already active")
        available = torch.nonzero(~self._state.active_mask[batch_index], as_tuple=False)
        if len(available) == 0:
            raise RuntimeError("no free tensor slot remains")
        slot = int(available[0].item())
        self._state = self._state_with_slot(
            batch_index,
            slot,
            passenger_id=passenger_id,
            position=position,
            target=target,
            radius=radius,
            desired_speed=desired_speed,
            level_index=level_index,
        )
        mapping[passenger_id] = slot
        return slot

    def remove(self, passenger_id: int, *, batch_index: int = 0) -> None:
        mapping = self._id_to_slot[batch_index]
        slot = mapping.pop(passenger_id, None)
        if slot is None:
            raise KeyError(f"passenger {passenger_id} is not active")
        self._state = self._state_with_slot(
            batch_index,
            slot,
            passenger_id=-1,
            position=(0.0, 0.0),
            target=(0.0, 0.0),
            radius=0.0,
            desired_speed=0.0,
            level_index=-1,
        )

    def active_ids(self, *, batch_index: int = 0) -> set[int]:
        return set(self._id_to_slot[batch_index])

    def slot_for(self, passenger_id: int, *, batch_index: int = 0) -> int | None:
        """Return the stable slot for a retained passenger, if any."""
        return self._id_to_slot[batch_index].get(passenger_id)

    def _state_with_slot(
        self,
        batch_index: int,
        slot: int,
        *,
        passenger_id: int,
        position: tuple[float, float],
        target: tuple[float, float],
        radius: float,
        desired_speed: float,
        level_index: int,
    ) -> PopulationState:
        state = self._state
        tensors = {
            "position": state.position.clone(),
            "velocity": state.velocity.clone(),
            "target": state.target.clone(),
            "radius": state.radius.clone(),
            "desired_speed": state.desired_speed.clone(),
            "active_mask": state.active_mask.clone(),
            "level_index": state.level_index.clone(),
            "passenger_ids": state.passenger_ids.clone(),
        }
        device, dtype = state.device, state.dtype
        active = passenger_id >= 0
        tensors["position"][batch_index, slot] = torch.tensor(position, device=device, dtype=dtype)
        tensors["velocity"][batch_index, slot] = 0.0
        tensors["target"][batch_index, slot] = torch.tensor(target, device=device, dtype=dtype)
        tensors["radius"][batch_index, slot, 0] = radius
        tensors["desired_speed"][batch_index, slot, 0] = desired_speed
        tensors["active_mask"][batch_index, slot] = active
        tensors["level_index"][batch_index, slot] = level_index
        tensors["passenger_ids"][batch_index, slot] = passenger_id
        return replace(state, **tensors)
