using System;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class StationDecorationPlacement
    {
        private readonly RuntimeGltfPrototypeLibrary _library;
        private readonly Transform _stationRoot;
        private readonly Transform _decorationRoot;
        private readonly ReplayData _data;
        private int _count;

        public StationDecorationPlacement(
            RuntimeGltfPrototypeLibrary library,
            Transform stationRoot,
            ReplayData data)
        {
            _library = library;
            _stationRoot = stationRoot;
            _data = data;
            _decorationRoot = new GameObject("CC0_Decorations").transform;
            _decorationRoot.SetParent(stationRoot, false);
        }

        public int Build()
        {
            foreach (var entity in _data.Entities)
                DecorateEntity(entity);
            foreach (var level in _data.Levels)
                AddLevelFixtures(level);
            return _count;
        }

        private void DecorateEntity(ReplayEntity entity)
        {
            var label = entity.Label ?? string.Empty;
            if (label.IndexOf("bench", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                ReplaceBench(entity);
                return;
            }
            if (label.IndexOf("ticket machine", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                DecorateTicketBank(entity);
                return;
            }
            if (label.IndexOf("planter", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                AddPlants(entity);
                return;
            }
            if (label.IndexOf("service center", StringComparison.OrdinalIgnoreCase) >= 0
                || label.IndexOf("restroom", StringComparison.OrdinalIgnoreCase) >= 0
                || label.IndexOf("shop", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                DecorateRoomBlock(entity, label.IndexOf("shop", StringComparison.OrdinalIgnoreCase) >= 0);
                return;
            }
            if (label.IndexOf("station sign", StringComparison.OrdinalIgnoreCase) >= 0)
                AddDisplays(entity, 2, 1.15f);
            if (string.Equals(entity.Kind, "entrance", StringComparison.OrdinalIgnoreCase))
                AddEntranceTrashCan(entity);
        }

        private void ReplaceBench(ReplayEntity entity)
        {
            var generated = _stationRoot.Find(entity.Id);
            if (generated != null && generated.TryGetComponent<Renderer>(out var renderer))
                renderer.enabled = false;
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out var size, out var longAxis, out var length);
            var seats = Mathf.Clamp(Mathf.FloorToInt(length / 2.2f), 1, 3);
            for (var i = 0; i < seats; i++)
            {
                var offset = (i - (seats - 1) * 0.5f) * Mathf.Min(2f, length / seats);
                Place(DecorationAssetKeys.Bench, center + longAxis * offset, StationDecorationGeometry.RotationFor(longAxis), 0.82f);
            }
            var endOffset = Mathf.Max(0.65f, length * 0.5f - 0.45f);
            Place(DecorationAssetKeys.TrashCan, center + longAxis * endOffset, Quaternion.identity, 0.78f);
        }

        private void DecorateTicketBank(ReplayEntity entity)
        {
            ElevateGeneratedBlock(entity, 2.2f);
            AddDisplays(entity, 4, 0.95f);
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out _, out var longAxis, out var length);
            Place(DecorationAssetKeys.CoffeeMachine, center + longAxis * (length * 0.35f), Quaternion.identity, 0.9f);
        }

        private void AddPlants(ReplayEntity entity)
        {
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out _, out var longAxis, out var length);
            for (var i = -1; i <= 1; i++)
                Place(DecorationAssetKeys.Plant, center + longAxis * i * Mathf.Min(1.1f, length * 0.22f), Quaternion.identity, 0.95f);
        }

        private void DecorateRoomBlock(ReplayEntity entity, bool isShop)
        {
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out var size, out var longAxis, out _);
            var shortAxis = Mathf.Abs(longAxis.x) > 0.5f ? Vector3.forward : Vector3.right;
            var edge = Mathf.Abs(shortAxis.x) > 0.5f ? size.x : size.z;
            Place(DecorationAssetKeys.Doorway, center - shortAxis * edge * 0.5f, StationDecorationGeometry.RotationFor(longAxis), 2.15f);
            if (isShop)
                Place(DecorationAssetKeys.CoffeeMachine, center + longAxis * 1.2f, Quaternion.identity, 1.0f);
        }

        private void AddDisplays(ReplayEntity entity, int count, float height)
        {
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out _, out var longAxis, out var length);
            for (var i = 0; i < count; i++)
            {
                var offset = (i - (count - 1) * 0.5f) * Mathf.Min(2f, length / count);
                Place(DecorationAssetKeys.Display, center + longAxis * offset, StationDecorationGeometry.RotationFor(longAxis), height);
            }
        }

        private void AddEntranceTrashCan(ReplayEntity entity)
        {
            StationDecorationGeometry.GetPlanarLayout(_data, entity, out var center, out _, out var longAxis, out var length);
            Place(DecorationAssetKeys.TrashCan, center + longAxis * Mathf.Min(1.2f, length * 0.35f), Quaternion.identity, 0.78f);
        }

        private void AddLevelFixtures(ReplayLevel level)
        {
            StationDecorationGeometry.GetLevelBounds(_data, level, out var center, out var size);
            for (var x = -1; x <= 1; x++)
            {
                for (var z = -1; z <= 1; z += 2)
                {
                    var position = center + new Vector3(size.x * 0.28f * x, 3.25f, size.z * 0.22f * z);
                    Place(DecorationAssetKeys.CeilingLamp, position, Quaternion.Euler(180f, 0f, 0f), 0.22f);
                }
            }

            var cameraA = center + new Vector3(-size.x * 0.42f, 2.8f, -size.z * 0.38f);
            var cameraB = center + new Vector3(size.x * 0.42f, 2.8f, size.z * 0.38f);
            PlaceFacing(DecorationAssetKeys.SecurityCamera, cameraA, center, 0.48f);
            PlaceFacing(DecorationAssetKeys.SecurityCamera, cameraB, center, 0.48f);
            Place(DecorationAssetKeys.FireExtinguisher, center + new Vector3(-size.x * 0.36f, 0.02f, 0f), Quaternion.identity, 0.72f);
            Place(DecorationAssetKeys.FireExtinguisher, center + new Vector3(size.x * 0.36f, 0.02f, 0f), Quaternion.identity, 0.72f);
        }

        private void ElevateGeneratedBlock(ReplayEntity entity, float height)
        {
            var generated = _stationRoot.Find(entity.Id);
            if (generated == null)
                return;
            var level = _data.GetLevel(entity.LevelIds[0]);
            var scale = generated.localScale;
            generated.localScale = new Vector3(scale.x, height, scale.z);
            generated.position = new Vector3(generated.position.x, level.Elevation + height * 0.5f, generated.position.z);
        }

        private void Place(string key, Vector3 position, Quaternion rotation, float height)
        {
            var instance = _library.Create(key, _decorationRoot);
            instance.transform.SetPositionAndRotation(position, rotation);
            instance.transform.localScale = Vector3.one * height;
            _count++;
        }

        private void PlaceFacing(string key, Vector3 position, Vector3 target, float height)
        {
            var direction = target - position;
            Place(key, position, Quaternion.LookRotation(direction.normalized, Vector3.up), height);
        }

    }
}
