using System;
using System.Collections.Generic;
using MetroReplay.Application;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class ElevatorReplayPresenter
    {
        private const string CarName = "ElevatorCar";
        private readonly List<ElevatorBinding> _bindings = new List<ElevatorBinding>();

        public int ElevatorCount => _bindings.Count;

        public ElevatorReplayPresenter(Transform stationRoot, ReplayData data)
        {
            if (stationRoot == null)
                throw new ArgumentNullException(nameof(stationRoot));
            if (data == null)
                throw new ArgumentNullException(nameof(data));

            foreach (var entity in data.Entities)
            {
                if (!string.Equals(entity.Kind, "elevator", StringComparison.OrdinalIgnoreCase))
                    continue;
                var elevatorRoot = stationRoot.Find(entity.Id);
                var car = elevatorRoot != null ? elevatorRoot.Find(CarName) : null;
                if (car == null)
                    continue;

                var sampler = new ElevatorReplaySampler(data, entity.Id);
                if (sampler.HasEvents)
                    _bindings.Add(new ElevatorBinding(car, sampler));
            }
        }

        public void Sync(float time)
        {
            for (var index = 0; index < _bindings.Count; index++)
            {
                var binding = _bindings[index];
                if (binding.Sampler.TrySample(time, out var sample))
                    binding.Car.position = sample.AnchorPosition;
            }
        }

        private readonly struct ElevatorBinding
        {
            public Transform Car { get; }
            public ElevatorReplaySampler Sampler { get; }

            public ElevatorBinding(Transform car, ElevatorReplaySampler sampler)
            {
                Car = car;
                Sampler = sampler;
            }
        }
    }
}
